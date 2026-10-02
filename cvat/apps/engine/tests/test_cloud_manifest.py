# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import os
import threading
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from unittest import mock

from django.db import connections
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITransactionTestCase

from cvat.apps.engine import cloud_manifest
from cvat.apps.engine.cloud_provider import S3CloudStorageClient, Status
from cvat.apps.engine.models import CloudStorage
from cvat.apps.engine.tests.utils import ForceLogin, generate_image_file
from cvat.apps.iam.models import User
from cvat.apps.iam.permissions import OpenPolicyAgentPermission, PermissionResult
from utils.dataset_manifest import ImageManifestManager
from utils.dataset_manifest.utils import find_related_images

LOCMEM_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "media": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

MANIFEST_KEY = "manifest.jsonl"
BASE_MTIME = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


class MockS3Client(S3CloudStorageClient):
    _files: dict[str, bytes] = {}
    _mtimes: dict[str, datetime] = {}
    download_calls: dict[str, int] = {}

    def get_status(self):
        return Status.AVAILABLE

    def get_file_status(self, key: str, /):
        return Status.AVAILABLE if key in self._files else Status.NOT_FOUND

    def get_file_last_modified(self, key: str, /):
        return self._mtimes[key]

    def _download_fileobj_to_stream(self, key: str, stream: BinaryIO, /):
        stream.write(self._files[key])

    def download_file(self, key: str, path: Path, /) -> None:
        super().download_file(key, path)
        self.download_calls[key] = self.download_calls.get(key, 0) + 1

    def download_fileobj(self, key: str, /) -> bytes:
        return self._files[key]

    def _download_range_of_bytes(self, key: str, /, *, stop_byte: int, start_byte: int = 0):
        return self._files[key][start_byte : stop_byte + 1]

    def get_file_stream(self, key: str, /, *, offset: int) -> tuple[BytesIO, int]:
        stream = BytesIO(self._files[key])
        stream.seek(offset)
        return stream, len(self._files[key])

    def bulk_delete(self, files) -> None:
        for key in files:
            self._files.pop(key, None)
            self._mtimes.pop(key, None)

    def _list_raw_content_on_one_page(
        self,
        prefix: str = "",
        *,
        next_token: str | None = None,
        page_size: int = 100,
    ) -> dict:
        raise NotImplementedError


def make_manifest_bytes(image_names: list[str], root_dir: Path) -> bytes:
    sources = []
    for name in image_names:
        image_path = root_dir / name
        image_path.parent.mkdir(parents=True, exist_ok=True)
        buffer = generate_image_file(os.path.basename(name))
        image_path.write_bytes(buffer.getvalue())
        sources.append(image_path)

    scenes, related_images = find_related_images(sources, root_path=root_dir)

    manifest_path = root_dir / "generated" / MANIFEST_KEY
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = ImageManifestManager(manifest_path, create_index=False)
    manifest.link(
        sources=[p for p in sources if p.relative_to(root_dir) in scenes],
        use_image_hash=True,
        data_dir=root_dir,
        meta={k: {"related_images": related_images[k]} for k in related_images},
        stop=len(sources) - 1,
    )
    manifest.create()
    return manifest_path.read_bytes()


@override_settings(CACHES=LOCMEM_CACHES)
class CloudManifestGenerationTestCase(APITransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._aws_patch = mock.patch(
            "cvat.apps.engine.cloud_provider.S3CloudStorageClient", MockS3Client
        )
        cls._aws_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._aws_patch.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username="owner", password="owner")
        self.client = APIClient()
        self.mtime = BASE_MTIME
        MockS3Client._files = {}
        MockS3Client._mtimes = {}
        MockS3Client.download_calls = {}
        self.files_dir = Path(__file__).parent / "_tmp_cloud_manifest"
        self.files_dir.mkdir(parents=True, exist_ok=True)

        # The policy engine (OPA/Regal) is not available in the unit test environment
        self._allow_patch = mock.patch.object(
            OpenPolicyAgentPermission,
            "check_access",
            lambda self: PermissionResult(allow=True, reasons=[]),
        )
        self._filter_patch = mock.patch.object(
            OpenPolicyAgentPermission,
            "filter",
            lambda self, queryset: queryset,
        )
        self._allow_patch.start()
        self._filter_patch.start()

    def tearDown(self):
        import shutil

        self._allow_patch.stop()
        self._filter_patch.stop()
        shutil.rmtree(self.files_dir, ignore_errors=True)
        super().tearDown()

    def put_remote_manifest(self, image_names: list[str], *, bump_mtime: bool = True):
        if bump_mtime:
            self.mtime = self.mtime + timedelta(seconds=10)
        local_dir = self.files_dir / f"gen_{len(MockS3Client._mtimes)}"
        content = make_manifest_bytes(image_names, local_dir)
        MockS3Client._files[MANIFEST_KEY] = content
        MockS3Client._mtimes[MANIFEST_KEY] = self.mtime
        # Put the referenced images into the "bucket" as well
        for name in image_names:
            image_path = local_dir / name
            if image_path.is_file():
                MockS3Client._files.setdefault(name, image_path.read_bytes())
                MockS3Client._mtimes.setdefault(name, self.mtime)
        return content

    def create_cloud_storage(self, *, manifests=None):
        data = {
            "provider_type": "AWS_S3_BUCKET",
            "resource": "test",
            "display_name": "Bucket",
            "credentials_type": "KEY_SECRET_KEY_PAIR",
            "key": "minio_access_key",
            "secret_key": "minio_secret_key",
            "specific_attributes": "endpoint_url=http://minio:9000",
            "description": "Some description",
            "manifests": manifests if manifests is not None else [MANIFEST_KEY],
        }
        with ForceLogin(self.owner, self.client):
            response = self.client.post("/api/cloudstorages", data=data, format="json")
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, (response.status_code, response.content)
        )
        return response.json()["id"]

    def get_content(self, storage_id, **params):
        with ForceLogin(self.owner, self.client):
            return self.client.get(
                f"/api/cloudstorages/{storage_id}/content-v2", data=params
            )

    def get_db_manifest(self, storage_id):
        return CloudStorage.objects.get(pk=storage_id).manifests.get(filename=MANIFEST_KEY)

    def test_publish_is_noop_when_remote_unchanged(self):
        self.put_remote_manifest(["a.jpg", "b.jpg"])
        storage_id = self.create_cloud_storage()

        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        db_manifest = self.get_db_manifest(storage_id)
        self.assertEqual(db_manifest.generation, 1)
        self.assertTrue((self._snapshot_path(db_manifest)).is_file())
        downloads_after_first_publish = MockS3Client.download_calls[MANIFEST_KEY]

        # Repeated requests must not trigger any downloads or new generations
        for _ in range(3):
            response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        db_manifest.refresh_from_db()
        self.assertEqual(db_manifest.generation, 1)
        self.assertEqual(
            MockS3Client.download_calls[MANIFEST_KEY], downloads_after_first_publish
        )

        # The legacy flat layout must not be (re)created
        legacy_path = CloudStorage.objects.get(pk=storage_id).get_storage_dirname() / MANIFEST_KEY
        self.assertFalse(legacy_path.exists())

    def test_pagination_is_bound_to_one_generation(self):
        self.put_remote_manifest(["a.jpg", "b.jpg", "c.jpg"])
        storage_id = self.create_cloud_storage()
        manifest_id = self.get_db_manifest(storage_id).id

        response = self.get_content(
            storage_id, manifest_path=MANIFEST_KEY, page_size=2
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first_page = response.json()
        self.assertEqual([i["name"] for i in first_page["content"]], ["a.jpg", "b.jpg"])
        self.assertEqual(
            first_page["next"],
            cloud_manifest.encode_manifest_page_token(manifest_id, 1, 2),
        )

        response = self.get_content(
            storage_id, manifest_path=MANIFEST_KEY, page_size=2, next_token=first_page["next"]
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        second_page = response.json()
        self.assertEqual([i["name"] for i in second_page["content"]], ["c.jpg"])
        self.assertIsNone(second_page["next"])

        # Admin replaces the remote manifest while the client keeps paging
        self.put_remote_manifest(["x.jpg", "y.jpg", "z.jpg"])

        response = self.get_content(
            storage_id,
            manifest_path=MANIFEST_KEY,
            page_size=2,
            next_token=first_page["next"],
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

        # Starting over binds to the new generation, pages are not mixed
        response = self.get_content(
            storage_id, manifest_path=MANIFEST_KEY, page_size=2
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        new_first_page = response.json()
        self.assertEqual([i["name"] for i in new_first_page["content"]], ["x.jpg", "y.jpg"])
        self.assertEqual(
            new_first_page["next"],
            cloud_manifest.encode_manifest_page_token(manifest_id, 2, 2),
        )

        db_manifest = self.get_db_manifest(storage_id)
        self.assertEqual(db_manifest.generation, 2)

        # Legacy (bare integer) tokens are accepted and bind to the current generation
        response = self.get_content(
            storage_id, manifest_path=MANIFEST_KEY, page_size=2, next_token="2"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([i["name"] for i in response.json()["content"]], ["z.jpg"])
        self.assertIsNone(response.json()["next"])

    def test_failed_refresh_never_exposes_half_files(self):
        self.put_remote_manifest(["a.jpg", "b.jpg"])
        storage_id = self.create_cloud_storage()

        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        db_manifest = self.get_db_manifest(storage_id)
        self.assertEqual(db_manifest.generation, 1)
        valid_snapshot = self._snapshot_path(db_manifest)
        self.assertTrue(valid_snapshot.is_file())

        # Remote object is replaced with an invalid manifest
        self.mtime = self.mtime + timedelta(seconds=10)
        MockS3Client._files[MANIFEST_KEY] = b"this is not a manifest at all"
        MockS3Client._mtimes[MANIFEST_KEY] = self.mtime

        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        db_manifest.refresh_from_db()
        self.assertEqual(db_manifest.generation, 1)
        self.assertTrue(valid_snapshot.is_file())
        valid_manifest = ImageManifestManager(valid_snapshot, valid_snapshot.parent)
        valid_manifest.set_index()
        self.assertEqual(list(valid_manifest.data), ["a.jpg", "b.jpg"])

        # Retrying while the remote object is invalid converges to the same result
        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        db_manifest.refresh_from_db()
        self.assertEqual(db_manifest.generation, 1)

        # No half-published snapshots or staging directories are left behind
        snapshot_root = (
            CloudStorage.objects.get(pk=storage_id).get_storage_dirname() / "manifests"
        )
        generation_files = sorted(
            p.name for p in (snapshot_root / str(db_manifest.id) / "1").iterdir()
        )
        self.assertEqual(generation_files, ["index.json", "manifest.jsonl"])
        staging_root = snapshot_root / ".staging"
        self.assertTrue(not staging_root.exists() or not any(staging_root.iterdir()))

        # Once the remote object is valid again, a new complete generation is published
        self.put_remote_manifest(["a.jpg", "b.jpg", "c.jpg"])
        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        db_manifest.refresh_from_db()
        self.assertEqual(db_manifest.generation, 2)
        self.assertEqual(
            [i["name"] for i in response.json()["content"]], ["a.jpg", "b.jpg", "c.jpg"]
        )

    def test_concurrent_refresh_publishes_single_generation(self):
        self.put_remote_manifest(["a.jpg"])
        storage_id = self.create_cloud_storage()
        self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        downloads_before = MockS3Client.download_calls[MANIFEST_KEY]

        self.put_remote_manifest(["a.jpg", "b.jpg"])
        db_storage = CloudStorage.objects.get(pk=storage_id)
        db_manifest = db_storage.manifests.get(filename=MANIFEST_KEY)

        barrier = threading.Barrier(5)
        results: list[cloud_manifest.PublishedManifest] = []
        errors: list[Exception] = []

        def refresh():
            barrier.wait()
            try:
                published = cloud_manifest.publish_cloud_manifest(db_storage, db_manifest)
                results.append(published)
            except Exception as ex:  # noqa: BLE001
                errors.append(ex)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=refresh) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 5)
        self.assertEqual({r.generation for r in results}, {2})
        self.assertEqual(len({str(r.snapshot_path) for r in results}), 1)
        # Exactly one actual download happened, retries converged
        self.assertEqual(MockS3Client.download_calls[MANIFEST_KEY], downloads_before + 1)

    def test_deregistered_manifest_does_not_resurrect(self):
        self.put_remote_manifest(["a.jpg"])
        storage_id = self.create_cloud_storage()
        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        db_storage = CloudStorage.objects.get(pk=storage_id)
        db_manifest = db_storage.manifests.get(filename=MANIFEST_KEY)
        snapshot_root = db_storage.get_storage_dirname() / "manifests" / str(db_manifest.id)
        self.assertTrue(snapshot_root.is_dir())

        # Simulate a leftover copy from the legacy flat layout
        legacy_path = db_storage.get_storage_dirname() / MANIFEST_KEY
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_bytes(b"legacy copy")

        with ForceLogin(self.owner, self.client):
            response = self.client.patch(
                f"/api/cloudstorages/{storage_id}",
                data={"manifests": []},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        self.assertFalse(snapshot_root.exists())
        self.assertFalse(legacy_path.exists())

        # The removed manifest cannot be browsed anymore
        response = self.get_content(storage_id, manifest_path=MANIFEST_KEY)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preview_cache_key_follows_generations_and_preview_is_pinned(self):
        from cvat.apps.engine.cache import MediaCache

        self.put_remote_manifest(["a.jpg", "b.jpg"])
        storage_id = self.create_cloud_storage()
        db_storage = CloudStorage.objects.get(pk=storage_id)

        first = cloud_manifest.publish_manifest_by_filename(db_storage, MANIFEST_KEY)
        signature = cloud_manifest.get_manifests_generation_signature(db_storage)
        self.assertEqual(signature, ((first.manifest_id, 1),))
        first_key = cloud_manifest.make_cloud_preview_cache_key(db_storage, signature)
        self.assertEqual(first_key, f"cloudstorage_{storage_id}_preview_{first.manifest_id}-1")

        preview, mime = MediaCache()._prepare_cloud_preview(
            db_storage, [[str(first.snapshot_path), first.manifest_prefix, first.kind]]
        )
        self.assertTrue(len(preview.getvalue()) > 0)
        self.assertEqual(mime, "image/jpeg")

        # New generation -> new key; the old snapshot stays usable for pinned consumers
        self.put_remote_manifest(["a.jpg"])
        second = cloud_manifest.publish_manifest_by_filename(db_storage, MANIFEST_KEY)
        self.assertEqual(second.generation, 2)
        second_key = cloud_manifest.make_cloud_preview_cache_key(
            db_storage, cloud_manifest.get_manifests_generation_signature(db_storage)
        )
        self.assertNotEqual(first_key, second_key)
        self.assertTrue(first.snapshot_path.is_file())

    def test_tasks_bind_to_the_generation_published_at_creation(self):
        self.put_remote_manifest(["a.jpg", "b.jpg"])
        storage_id = self.create_cloud_storage()

        first_task_id = self._create_task(storage_id)
        with ForceLogin(self.owner, self.client):
            response = self.client.get(f"/api/tasks/{first_task_id}/data/meta")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [frame["name"] for frame in response.data["frames"]], ["a.jpg", "b.jpg"]
        )

        # The remote manifest is replaced while the first task already exists
        self.put_remote_manifest(["a.jpg"])
        self.get_content(storage_id, manifest_path=MANIFEST_KEY)

        second_task_id = self._create_task(storage_id)
        with ForceLogin(self.owner, self.client):
            response = self.client.get(f"/api/tasks/{second_task_id}/data/meta")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([frame["name"] for frame in response.data["frames"]], ["a.jpg"])

        # The first task still refers to the generation it was created from
        with ForceLogin(self.owner, self.client):
            response = self.client.get(f"/api/tasks/{first_task_id}/data/meta")
        self.assertEqual(
            [frame["name"] for frame in response.data["frames"]], ["a.jpg", "b.jpg"]
        )

    def _create_task(self, storage_id: int) -> int:
        with ForceLogin(self.owner, self.client):
            response = self.client.post("/api/tasks", data={"name": "gen task"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            task_id = response.data["id"]

            response = self.client.post(
                f"/api/tasks/{task_id}/data",
                data={
                    "server_files[0]": MANIFEST_KEY,
                    "image_quality": 75,
                    "cloud_storage_id": storage_id,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
            rq_id = response.data["rq_id"]

            response = self.client.get(f"/api/requests/{rq_id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["status"], "finished", response.data["message"])

        return task_id

    def _snapshot_path(self, db_manifest) -> Path:
        storage = CloudStorage.objects.get(pk=db_manifest.cloud_storage_id)
        return storage.get_storage_dirname() / db_manifest.local_snapshot
