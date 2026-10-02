import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conftest  # noqa: F401

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_orm")

import django

django.setup()

import traceback

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=0)
old = runner.setup_databases()

from cvat.apps.engine.models import Project
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import (
    QualityRequirementAnnotationType,
    QualitySettings,
    ensure_base_quality_requirements,
)
from cvat.apps.quality_control.serializers import (
    QualityRequirementBulkCreateSerializer,
)

_orig_bump = generation.bump_rules_version
_calls = []


def _traced(settings):
    stack = traceback.format_stack(limit=8)
    _calls.append("".join(stack[-4:-1]))
    return _orig_bump(settings)


generation.bump_rules_version = _traced

project = Project.objects.create(name="p")
settings, _ = QualitySettings.objects.get_or_create(project=project)
ensure_base_quality_requirements(settings)
base_id = settings.requirements.filter(
    annotation_type=QualityRequirementAnnotationType.RECTANGLE
).first().id
serializer = QualityRequirementBulkCreateSerializer(
    data={
        "settings_id": settings.id,
        "requirements": [
            {"name": "bulk 1", "parent_requirement": base_id},
            {"name": "bulk 2", "parent_requirement": base_id},
        ],
    }
)
assert serializer.is_valid(raise_exception=True)
serializer.save()
settings.refresh_from_db()
print("version:", settings.rules_version)
for c in _calls:
    print("---")
    print(c)
