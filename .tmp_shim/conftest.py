import importlib.abc
import importlib.machinery
import sys
import types
from pathlib import Path

SHIM_DATUMARO = Path(__file__).parent / "datumaro"


class _DummyModuleLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return types.ModuleType(spec.name)

    def exec_module(self, module):
        def __getattr__(name):
            return type(name, (), {})

        module.__getattr__ = __getattr__


class _DatumaroDummyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("datumaro"):
            return None

        relative_parts = fullname.split(".")[1:]
        relative = SHIM_DATUMARO.joinpath(*relative_parts)
        if relative.with_suffix(".py").exists() or (
            relative / "__init__.py"
        ).exists():
            # Defer to the default FileFinder, which serves the shim package
            return None

        return importlib.util.spec_from_loader(
            fullname,
            _DummyModuleLoader(),
            is_package=True,
        )


sys.meta_path.insert(0, _DatumaroDummyFinder())


# Fallback for settings referenced at import (class body) time by the engine
# serializer chain. Production settings define every constant explicitly;
# the shim only needs non-failing, inert values for collection.
def _patch_django_settings_fallback():
    from django.conf import LazySettings

    original_getattr = LazySettings.__getattr__

    def __getattr__(self, name):
        try:
            return original_getattr(self, name)
        except AttributeError:
            if not name.isupper():
                raise
            if name in ("CACHES", "RQ_QUEUES"):
                value = {}
            elif name in ("EXPORT_JOB_RETRY_INTERVALS", "IMPORT_JOB_RETRY_INTERVALS"):
                value = (60, 120, 300)
            elif name.endswith(("_ROOT", "_DIR")):
                value = str(SHIM_DATUMARO / "tmp")
            elif name.endswith("ENABLED"):
                value = False
            elif name.endswith(
                (
                    "_TTL",
                    "_TIMEOUT",
                    "_SIZE",
                    "_COUNT",
                    "_LIMIT",
                    "_REPLICAS",
                    "_INTERVALS",
                    "_DAYS",
                    "_BATCH_SIZE",
                    "_MAX_PAGE_SIZE",
                )
            ) or name.startswith(("MAX_", "DEFAULT_DB_", "CVAT_CHUNK", "CVAT_CACHE_ITEM")):
                value = 0
            else:
                value = None
            object.__setattr__(self, name, value)
            return value

    LazySettings.__getattr__ = __getattr__


_patch_django_settings_fallback()
