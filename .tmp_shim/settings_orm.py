from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SHIM_DIR = BASE_DIR / ".tmp_shim"

SECRET_KEY = "orm-shim-secret-key"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "shimapps.EngineConfig",
    "shimapps.OrganizationsConfig",
    "shimapps.QualityControlConfig",
    "shimapps.IamConfig",
    "shimapps.WebhooksConfig",
    "rest_framework_api_key",
    "shimapps.AccessTokensConfig",
]

# Create tables directly from current models instead of the (partially missing)
# migration graph in this checkout
MIGRATION_MODULES = {
    "engine": None,
    "organizations": None,
    "quality_control": None,
    "iam": None,
    "webhooks": None,
    "access_tokens": None,
}

AUTH_USER_MODEL = "iam.User"
DEFAULT_DB_BULK_CREATE_BATCH_SIZE = 1000
ONE_RUNNING_JOB_IN_QUEUE_PER_USER = False
MEDIA_CACHE_ALLOW_STATIC_CACHE = False
CVAT_CACHE_ITEM_MAX_SIZE = 500 * 1024 * 1024
CVAT_CHUNK_CREATE_TIMEOUT = 50
CVAT_CHUNK_CREATE_CHECK_INTERVAL = 0.2
EXPORT_JOB_RETRY_INTERVALS = (60, 120, 300)
IMPORT_JOB_RETRY_INTERVALS = (60, 120, 300)
MAX_CONSENSUS_REPLICAS = 11
DEFAULT_DB_ANNO_CHUNK_SIZE = 2000
MAX_JOBS_PER_TASK = 5000
SMOKESCREEN_ENABLED = False
SILENCED_SYSTEM_CHECKS = []
RQ_QUEUES = {}
REST_FRAMEWORK = {}
SERIALIZATION_MODULES = {}
BUCKET_CONTENT_MAX_PAGE_SIZE = 1000
CVAT_PREVIEW_CACHE_TTL = 30
TMP_FILES_ROOT = str(SHIM_DIR / "tmp")
MAX_QUALITY_REQUIREMENTS_PER_SETTINGS = 100

from enum import Enum as _Enum
from types import SimpleNamespace as _SimpleNamespace


class _CVAT_QUEUES(_Enum):
    IMPORT_DATA = "import"
    EXPORT_DATA = "export"
    AUTO_ANNOTATION = "annotation"
    WEBHOOKS = "webhooks"
    NOTIFICATIONS = "notifications"
    QUALITY_REPORTS = "quality_reports"
    CLEANING = "cleaning"
    CHUNKS = "chunks"
    CONSENSUS = "consensus"


CVAT_QUEUES = _SimpleNamespace(
    **{member.name: _SimpleNamespace(value=member.value) for member in _CVAT_QUEUES}
)


def __getattr__(name):
    if name == "CACHES":
        return {}
    if name.endswith("_ROOT"):
        return str(SHIM_DIR / name.lower().removesuffix("_root"))
    if name in ("EXPORT_JOB_RETRY_INTERVALS", "IMPORT_JOB_RETRY_INTERVALS"):
        return (60, 120, 300)
    if name.endswith("ENABLED"):
        return False
    if name.endswith(
        (
            "_TTL",
            "_TIMEOUT",
            "_SIZE",
            "_COUNT",
            "_LIMIT",
            "_REPLICAS",
            "_INTERVALS",
            "_BATCH_SIZE",
            "_MAX_PAGE_SIZE",
        )
    ) or name.startswith(("MAX_", "DEFAULT_DB_", "CVAT_CHUNK", "CVAT_CACHE_ITEM")):
        return 0
    return None

