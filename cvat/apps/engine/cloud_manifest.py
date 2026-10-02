# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Generation-based publishing of cloud storage manifests.

A cloud storage manifest can be replaced on the remote bucket at any moment.
Historically, manifest browsing, preview generation and task creation each
downloaded the remote file independently, straight into a shared local path.
As a result, pagination tokens, previews and task file selection could refer to
different contents of the same remote manifest, and a failed download/parsing
could leave a half-written file in place of the previously valid one.

This module makes manifest refreshes atomic "generation publications":

* a refresh downloads the remote object into an isolated staging directory,
* the staged file is fully parsed before it is exposed,
* only a complete snapshot is moved to an immutable, generation-keyed path,
* the publication (filesystem snapshot + database metadata) is performed under
  a per-manifest lock, so concurrent refreshes converge to a single generation.

Browsing tokens, preview cache entries and task creation are then bound to the
generation they were started with.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

import attrs
import django_rq
from django.conf import settings
from django.db import transaction
from redis.exceptions import LockError
from rest_framework.exceptions import NotFound, ValidationError

from cvat.apps.engine.log import ServerLogManager
from utils.dataset_manifest import ImageManifestManager, VideoManifestManager
from utils.dataset_manifest.core import is_dataset_manifest, is_video_manifest

slogger = ServerLogManager(__name__)

ManifestKind = Literal["images", "video"]

_SNAPSHOT_ROOT = "manifests"
_STAGING_DIR = ".staging"
_MANIFEST_FILE_NAME = "manifest.jsonl"
_INDEX_FILE_NAME = "index.json"
# Number of immutable generation snapshots to keep for a single manifest.
# The extra generation allows already started operations (e.g. preview
# preparation running in a worker) to finish against a pinned snapshot.
_RETAINED_GENERATIONS = 2

_PAGE_TOKEN_RE = re.compile(r"^m(?P<manifest_id>\d+)\.(?P<generation>\d+)\.(?P<offset>\d+)$")


@attrs.frozen
class PublishedManifest:
    manifest_id: int
    cloud_storage_id: int
    filename: str
    generation: int
    snapshot_path: Path
    remote_last_modified: datetime
    kind: ManifestKind

    @property
    def manifest_prefix(self) -> str:
        return os.path.dirname(self.filename)


def _manifest_root(db_storage, db_manifest) -> Path:
    return db_storage.get_storage_dirname() / _SNAPSHOT_ROOT / str(db_manifest.id)


def _generation_dir(db_storage, db_manifest, generation: int) -> Path:
    return _manifest_root(db_storage, db_manifest) / str(generation)


def _staging_dir(db_storage, db_manifest) -> Path:
    return _manifest_root(db_storage, db_manifest) / _STAGING_DIR / uuid.uuid4().hex


def _snapshot_relpath(db_storage, path: Path) -> str:
    return path.relative_to(db_storage.get_storage_dirname()).as_posix()


def _normalize_remote_mtime(value: datetime) -> datetime:
    if value.tzinfo is None:
        from django.utils.timezone import make_aware

        value = make_aware(value)
    return value


def get_published_manifest(db_storage, db_manifest) -> PublishedManifest | None:
    """
    Returns the currently published generation without contacting the remote
    storage, or None if no complete generation has been published yet.
    """
    if not db_manifest.generation or not db_manifest.local_snapshot:
        return None

    snapshot_path = db_storage.get_storage_dirname() / db_manifest.local_snapshot
    if not snapshot_path.is_file():
        return None

    kind: ManifestKind = "video" if is_video_manifest(snapshot_path) else "images"
    return PublishedManifest(
        manifest_id=db_manifest.id,
        cloud_storage_id=db_storage.id,
        filename=db_manifest.filename,
        generation=db_manifest.generation,
        snapshot_path=snapshot_path,
        remote_last_modified=db_manifest.remote_last_modified,
        kind=kind,
    )


def _validate_staged_manifest(staged_path: Path) -> ManifestKind:
    """
    Fully downloads and parses a staged manifest file.
    Only a manifest that passed this validation can be published.
    """
    if is_dataset_manifest(staged_path):
        kind: ManifestKind = "images"
        manager = ImageManifestManager(staged_path, staged_path.parent)
    elif is_video_manifest(staged_path):
        kind = "video"
        manager = VideoManifestManager(staged_path)
    else:
        raise ValidationError(f"The '{staged_path.name}' file is not a valid dataset manifest")

    try:
        manager.set_index()
        # Iterating over the manifest parses every single entry (and therefore
        # every JSON line), so a truncated or otherwise corrupted file is
        # rejected here, before it can be published.
        for _ in manager:
            pass
    except (ValueError, KeyError) as ex:
        raise ValidationError(
            f"The '{staged_path.name}' file is not a valid dataset manifest"
        ) from ex

    return kind


def _iter_generation_dirs(root: Path) -> Iterator[tuple[int, Path]]:
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.isdigit() and entry.name != "0":
            yield int(entry.name), entry


def _prune_old_generations(db_storage, db_manifest, current_generation: int) -> None:
    root = _manifest_root(db_storage, db_manifest)
    retained = {
        current_generation - i for i in range(_RETAINED_GENERATIONS) if current_generation - i > 0
    }
    for generation, path in _iter_generation_dirs(root):
        if generation not in retained:
            shutil.rmtree(path, ignore_errors=True)
            slogger.glob.info(
                f"Removed outdated cloud manifest generation {generation} "
                f"of manifest {db_manifest.id} ({db_manifest.filename})"
            )


def _remove_legacy_layout(db_storage, filename: str) -> None:
    """
    Removes files left from the legacy flat manifest layout
    (<storage dir>/<manifest filename> and the sibling index.json).
    Such files must not be used anymore and must not be able to "resurrect".
    """
    storage_dir = db_storage.get_storage_dirname()
    legacy_path = storage_dir / filename
    try:
        if (
            legacy_path.is_file()
            and _SNAPSHOT_ROOT not in legacy_path.relative_to(storage_dir).parts
        ):
            legacy_path.unlink()
    except OSError:
        slogger.glob.warning(
            f"Failed to remove legacy cloud manifest file {legacy_path}", exc_info=True
        )

    legacy_index = legacy_path.parent / _INDEX_FILE_NAME
    try:
        if (
            legacy_index.is_file()
            and _SNAPSHOT_ROOT not in legacy_index.relative_to(storage_dir).parts
        ):
            legacy_index.unlink()
    except OSError:
        slogger.glob.warning(
            f"Failed to remove legacy cloud manifest index {legacy_index}", exc_info=True
        )


def publish_cloud_manifest(
    db_storage,
    db_manifest,
    *,
    storage_client=None,
) -> PublishedManifest:
    """
    Ensures that the published generation of the manifest matches the remote
    object.

    * If the remote manifest has not been modified, the current generation is
      returned without any downloads.
    * Otherwise a new generation is downloaded, fully validated and atomically
      published. A failed download or parsing never replaces the previously
      published generation.
    * Concurrent calls for the same manifest are serialized and converge to the
      same generation.
    """
    from cvat.apps.engine.models import Manifest

    if storage_client is None:
        storage_client = db_storage.get_client()

    redis_connection = django_rq.get_queue(settings.CVAT_QUEUES.CHUNKS.value).connection
    lock_name = f"lock-cloud-manifest-{db_storage.id}-{db_manifest.id}"
    lock = redis_connection.lock(lock_name, timeout=60, blocking_timeout=50)

    acquired = lock.acquire()
    if not acquired:
        raise LockError(f"Cannot acquire lock for the manifest '{db_manifest.filename}'")

    staging = None
    try:
        # Re-read the state under the lock: another request may have already
        # published the up-to-date generation.
        with transaction.atomic():
            locked_manifest = (
                Manifest.objects.select_for_update()
                .select_related("cloud_storage")
                .get(pk=db_manifest.pk)
            )

            remote_last_modified = _normalize_remote_mtime(
                storage_client.get_file_last_modified(locked_manifest.filename)
            )

            published = get_published_manifest(db_storage, locked_manifest)
            if (
                published is not None
                and locked_manifest.remote_last_modified == remote_last_modified
            ):
                return published

            new_generation = locked_manifest.generation + 1
            target_dir = _generation_dir(db_storage, locked_manifest, new_generation)

        # Download and validate outside of the database transaction.
        staging = _staging_dir(db_storage, locked_manifest)
        staging.mkdir(parents=True, exist_ok=False)
        staged_manifest_path = staging / _MANIFEST_FILE_NAME
        try:
            storage_client.download_file(locked_manifest.filename, staged_manifest_path)
            kind = _validate_staged_manifest(staged_manifest_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            try:
                os.removedirs(staging.parent)
            except OSError:
                pass
            staging = None
            raise

        # Atomically place the complete snapshot at its immutable generation path.
        try:
            os.makedirs(target_dir, exist_ok=False)
            os.replace(staging / _MANIFEST_FILE_NAME, target_dir / _MANIFEST_FILE_NAME)
            staged_index = staging / _INDEX_FILE_NAME
            if staged_index.is_file():
                os.replace(staged_index, target_dir / _INDEX_FILE_NAME)
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)
        try:
            os.removedirs(staging.parent)
        except OSError:
            pass
        staging = None

        snapshot_relpath = _snapshot_relpath(db_storage, target_dir / _MANIFEST_FILE_NAME)

        with transaction.atomic():
            locked_manifest = Manifest.objects.select_for_update().get(pk=locked_manifest.pk)
            # Defense in depth: under the redis lock this state is not expected.
            already_published = get_published_manifest(db_storage, locked_manifest)
            if (
                already_published is not None
                and locked_manifest.remote_last_modified == remote_last_modified
            ):
                shutil.rmtree(target_dir, ignore_errors=True)
                return already_published

            locked_manifest.generation = new_generation
            locked_manifest.remote_last_modified = remote_last_modified
            locked_manifest.local_snapshot = snapshot_relpath
            locked_manifest.save()

        db_manifest.refresh_from_db()
        result = PublishedManifest(
            manifest_id=db_manifest.id,
            cloud_storage_id=db_storage.id,
            filename=db_manifest.filename,
            generation=new_generation,
            snapshot_path=target_dir / _MANIFEST_FILE_NAME,
            remote_last_modified=remote_last_modified,
            kind=kind,
        )

        _prune_old_generations(db_storage, db_manifest, new_generation)
        _remove_legacy_layout(db_storage, db_manifest.filename)

        return result
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        try:
            lock.release()
        except LockError:
            slogger.glob.warning(f"Failed to release lock {lock_name}", exc_info=True)


def get_registered_manifest(db_storage, filename: str):
    return db_storage.get_manifest(filename)


def publish_manifest_by_filename(
    db_storage, filename: str, *, storage_client=None
) -> PublishedManifest:
    """
    Resolves filename against the manifests configured for the storage and
    publishes (if needed) its current generation.
    Raises NotFound if the manifest is not registered for the storage, which
    prevents deregistered/legacy local copies from being used.
    """
    db_manifest = get_registered_manifest(db_storage, filename)
    if db_manifest is None:
        raise NotFound(
            f"The manifest file '{filename}' is not attached to the cloud storage "
            f"'{db_storage.display_name}'"
        )
    return publish_cloud_manifest(db_storage, db_manifest, storage_client=storage_client)


def discard_manifest_snapshots(db_storage, manifest_id: int, filename: str) -> None:
    """
    Drops all local state of a manifest that is being removed from the storage
    configuration, so its old snapshot (and legacy layout files) cannot be used
    after the manifest list is updated.
    """
    root = db_storage.get_storage_dirname() / _SNAPSHOT_ROOT / str(manifest_id)
    shutil.rmtree(root, ignore_errors=True)
    _remove_legacy_layout(db_storage, filename)


def encode_manifest_page_token(manifest_id: int, generation: int, offset: int) -> str:
    return f"m{manifest_id}.{generation}.{offset}"


def parse_manifest_page_token(token: str | None) -> tuple[int | None, int | None, int]:
    """
    Returns (manifest_id, generation, offset).
    For tokens emitted by older server versions (a bare non-negative integer)
    the manifest id and generation are None, i.e. the token is not pinned to a
    generation.
    Raises ValidationError for malformed tokens.
    """
    if not token:
        return None, None, 0

    match = _PAGE_TOKEN_RE.fullmatch(token)
    if match:
        return (
            int(match.group("manifest_id")),
            int(match.group("generation")),
            int(match.group("offset")),
        )

    if token.isdigit():
        return None, None, int(token)

    raise ValidationError("Wrong value for the next_token parameter was found.")


def get_manifests_generation_signature(db_storage) -> tuple[tuple[int, int], ...]:
    """
    Compact description of the currently published generations of all the
    manifests attached to the storage. It changes whenever a manifest is
    published, added or removed, and therefore identifies the "manifest view"
    of the storage.
    """
    return tuple(
        sorted(
            db_storage.manifests.values_list("id", "generation"),
        )
    )


def make_cloud_preview_cache_key(
    db_storage, signature: tuple[tuple[int, int], ...] | None = None
) -> str:
    if signature is None:
        signature = get_manifests_generation_signature(db_storage)

    base_key = f"cloudstorage_{db_storage.id}_preview"
    if not signature:
        return base_key

    generations = "_".join(f"{manifest_id}-{generation}" for manifest_id, generation in signature)
    return f"{base_key}_{generations}"
