import pytest

# Register signal receivers (the shim AppConfig skips ready())
import cvat.apps.quality_control.signals  # noqa: F401
from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import (
    QualityRequirement,
    QualityRequirementAnnotationType,
    QualitySettings,
)
from cvat.apps.quality_control.serializers import (
    QualityRequirementBulkCreateSerializer,
    QualityRequirementSerializer,
    QualitySettingsSerializer,
)


def _make_task(name="t", *, project=None):
    task = Task.objects.create(name=name, project=project)
    settings = QualitySettings.objects.get(task=task)
    # Base requirements are the initial content of rules version 1; seeding
    # them at creation does not bump.
    assert settings.rules_version == 1
    return task, settings


def _make_project():
    project = Project.objects.create(name="p")
    settings = QualitySettings.objects.get(project=project)
    assert settings.rules_version == 1
    return project, settings


@pytest.mark.django_db
def test_single_requirement_create_update_delete_bumps_once():
    task, settings = _make_task()
    assert settings.rules_version == 1

    serializer = QualityRequirementSerializer(
        data={
            "settings_id": settings.id,
            "name": "custom rect",
            "parent_requirement": settings.requirements.filter(
                annotation_type=QualityRequirementAnnotationType.RECTANGLE
            ).first().id,
        },
        context={"request": type("R", (), {"user": None})()},
    )
    assert serializer.is_valid(raise_exception=True)
    requirement = serializer.save()
    settings.refresh_from_db()
    assert settings.rules_version == 2
    assert QualityRequirement.objects.get(id=requirement.id).name == "custom rect"

    serializer2 = QualityRequirementSerializer(
        instance=requirement,
        data={"metric": "precision"},
        partial=True,
        context={"request": type("R", (), {"user": None})()},
    )
    assert serializer2.is_valid(raise_exception=True)
    serializer2.save()
    settings.refresh_from_db()
    assert settings.rules_version == 3

    # No-op requirement save without changes does not happen via API; deletion bumps
    from cvat.apps.quality_control.views import QualityRequirementViewSet

    QualityRequirementViewSet().perform_destroy(requirement)
    settings.refresh_from_db()
    assert settings.rules_version == 4


@pytest.mark.django_db
def test_settings_scalar_changes_bump():
    task, settings = _make_task()
    assert settings.rules_version == 1
    serializer = QualitySettingsSerializer(
        instance=settings,
        data={"max_validations_per_job": 3},
        partial=True,
    )
    assert serializer.is_valid(raise_exception=True)
    serializer.save()
    settings.refresh_from_db()
    assert settings.rules_version == 2
    assert settings.max_validations_per_job == 3

    # Saving unrelated / no changed scalars / no requirements does not bump
    serializer = QualitySettingsSerializer(
        instance=settings,
        data={"max_validations_per_job": 3},
        partial=True,
    )
    assert serializer.is_valid(raise_exception=True)
    serializer.save()
    settings.refresh_from_db()
    assert settings.rules_version == 2


@pytest.mark.django_db
def test_bulk_create_bumps_once():
    project, settings = _make_project()
    base_id = settings.requirements.filter(
        annotation_type=QualityRequirementAnnotationType.RECTANGLE
    ).first().id
    serializer = QualityRequirementBulkCreateSerializer(
        data={
            "settings_id": settings.id,
            "requirements": [
                {
                    "name": "bulk 1",
                    "parent_requirement": base_id,
                },
                {
                    "name": "bulk 2",
                    "parent_requirement": base_id,
                },
            ],
        }
    )
    assert serializer.is_valid(raise_exception=True)
    created = serializer.save()
    assert len(created) == 2
    settings.refresh_from_db()
    assert settings.rules_version == 2


@pytest.mark.django_db
def test_task_move_between_projects_bumps():
    project_1, _ = _make_project()
    project_2, _ = _make_project()
    task, settings = _make_task(project=project_1)
    assert settings.rules_version == 1

    task.project = project_2
    task.save()
    settings.refresh_from_db()
    assert settings.rules_version == 2

    # Saving the task again without changing the project does not bump
    task.save()
    settings.refresh_from_db()
    assert settings.rules_version == 2
