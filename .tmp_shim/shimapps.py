# Minimal AppConfigs that skip the heavy ready() hooks (OPA/schema/signals)
from django.apps import AppConfig


class EngineConfig(AppConfig):
    name = "cvat.apps.engine"


class OrganizationsConfig(AppConfig):
    name = "cvat.apps.organizations"


class QualityControlConfig(AppConfig):
    name = "cvat.apps.quality_control"

    def ready(self) -> None:
        # Connect the settings/requirements initialization and the
        # task project-move version bump signals, skipping the heavy
        # OPA/schema hooks that are irrelevant to offline model tests.
        from cvat.apps.quality_control import signals  # noqa: F401


class IamConfig(AppConfig):
    name = "cvat.apps.iam"


class WebhooksConfig(AppConfig):
    name = "cvat.apps.webhooks"


class AccessTokensConfig(AppConfig):
    name = "cvat.apps.access_tokens"
