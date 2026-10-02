import pytest

from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import (
    QualityRequirementAnnotationType,
    QualitySettings,
)


@pytest.mark.django_db
def test_generation_descriptor_and_bump():
    project = Project.objects.create(name="p")
    task = Task.objects.create(name="t", project=project)

    project_settings = QualitySettings.objects.get(project=project)
    task_settings = QualitySettings.objects.get(task=task)

    task_generation = generation.get_current_rules_generation(task=task)
    project_generation = generation.get_current_rules_generation(project=project)

    assert task_generation.inherit is True
    assert task_generation.source_settings_id == project_settings.id
    assert task_generation.fingerprint == project_generation.fingerprint
    assert task_generation.scope_settings_id == task_settings.id
    assert project_generation.inherit is False

    # Idempotent resolution
    assert generation.get_current_rules_generation(task=task).id == task_generation.id

    standalone_task = Task.objects.create(name="t2")
    standalone_settings = QualitySettings.objects.get(task=standalone_task)
    # A truly custom task differs from the project rule content
    standalone_settings.requirements.filter(
        annotation_type=QualityRequirementAnnotationType.RECTANGLE
    ).update(enabled=True)
    standalone_settings.save()

    standalone_generation = generation.get_current_rules_generation(task=standalone_task)
    assert standalone_generation.inherit is False
    assert standalone_generation.source_settings_id == standalone_settings.id
    assert standalone_generation.fingerprint != project_generation.fingerprint

    # Bumping project settings creates a new generation for the project and for
    # tasks inheriting from it
    generation.bump_rules_version(project_settings)
    project_generation_2 = generation.get_current_rules_generation(project=project)
    task_generation_2 = generation.get_current_rules_generation(task=task)
    assert project_generation_2.id != project_generation.id
    assert project_generation_2.source_rules_version == 2
    assert task_generation_2.fingerprint == project_generation_2.fingerprint
    assert task_generation_2.id != task_generation.id
    assert task_generation_2.source_settings_id == project_settings.id

    # The standalone task does not inherit, so its generation does not change
    assert (
        generation.get_current_rules_generation(task=standalone_task).id
        == standalone_generation.id
    )


@pytest.mark.django_db
def test_bump_rules_version_is_monotonic():
    project = Project.objects.create(name="p")
    settings = QualitySettings.objects.get(project=project)
    assert settings.rules_version == 1

    generation.bump_rules_version(settings)
    generation.bump_rules_version(settings)
    assert settings.rules_version == 3

    # No row - no crash, nothing to refresh
    settings.id = 999999
    assert generation.bump_rules_version(settings) == 0


@pytest.mark.django_db
def test_generation_is_rules_current():
    project = Project.objects.create(name="p")
    project_settings = QualitySettings.objects.get(project=project)

    current = generation.get_current_rules_generation(project=project)
    assert generation.is_rules_generation_current(current, project=project)

    generation.bump_rules_version(project_settings)
    new_current = generation.get_current_rules_generation(project=project)
    assert new_current.id != current.id
    assert not generation.is_rules_generation_current(current, project=project)
    assert generation.is_rules_generation_current(new_current, project=project)
