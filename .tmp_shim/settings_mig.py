from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SHIM_DIR = BASE_DIR / ".tmp_shim"

SECRET_KEY = "shim-secret-key"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(SHIM_DIR / "shim.sqlite3"),
    },
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "shimapps.EngineConfig",
    "shimapps.OrganizationsConfig",
    "shimapps.QualityControlConfig",
]

AUTH_USER_MODEL = "auth.User"
MIGRATIONS_LOGS_ROOT = str(SHIM_DIR / "logs")


def __getattr__(name):
    if name.endswith("_ROOT"):
        return str(SHIM_DIR / name.lower().removesuffix("_root"))
    return None

