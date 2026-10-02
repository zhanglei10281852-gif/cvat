# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control.models import (
    QualitySettings,
    ensure_base_quality_requirements,
)


def _ensure_base_requirements_for_task(task: Task) -> None:
    quality_settings, _ = QualitySettings.objects.get_or_create(task_id=task.id)
    ensure_base_quality_requirements(quality_settings)


def _ensure_base_requirements_for_project(project: Project) -> None:
    quality_settings, _ = QualitySettings.objects.get_or_create(project_id=project.id)
    ensure_base_quality_requirements(quality_settings)


@receiver(post_init, sender=Task)
def __init_task__track_project_for_quality_generation(instance: Task, **kwargs):
    # Tracked to bump the task settings rules version when the task is
    # moved between projects, which changes the effective inheritance source.
    instance._quality_rules_tracked_project_id = instance.project_id


@receiver(post_save, sender=Project)
def __save_project__initialize_quality_settings(
    instance: Project, created: bool, raw: bool, **kwargs
):
    if created and not raw:
        _ensure_base_requirements_for_project(instance)


@receiver(post_save, sender=Task)
def __save_task__initialize_quality_settings(instance: Task, created: bool, **kwargs):
    if created and not kwargs.get("raw"):
        _ensure_base_requirements_for_task(instance)
        return

    if kwargs.get("raw"):
        return

    tracked_project_id = getattr(instance, "_quality_rules_tracked_project_id", None)
    # Keep the tracker in sync even when the project did not change, so the
    # following task saves do not look like project moves.
    instance._quality_rules_tracked_project_id = instance.project_id

    if tracked_project_id == instance.project_id:
        return

    try:
        quality_settings = instance.quality_settings
    except QualitySettings.DoesNotExist:
        return

    from cvat.apps.quality_control.generation import bump_rules_version

    bump_rules_version(quality_settings)
