# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from django.test import TransactionTestCase

from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import (
    QualityReportStatus,
    QualityRequirement,
    QualityRequirementAnnotationType,
    QualitySettings,
    QualityRulesGeneration,
)
from cvat.apps.quality_control.serializers import QualityRequirementSerializer


class RulesGenerationTestCase(TransactionTestCase):
    def setUp(self):
        self.project = Project.objects.create(name="p")
        self.project_settings = QualitySettings.objects.get(project=self.project)
        self.task = Task.objects.create(name="t", project=self.project)
        self.task_settings = QualitySettings.objects.get(task=self.task)

        self.standalone_task = Task.objects.create(name="t2")
        self.standalone_settings = QualitySettings.objects.get(task=self.standalone_task)

    def test_inheritance_descriptor_and_fingerprint(self):
        task_generation = generation.get_current_rules_generation(task=self.task)
        project_generation = generation.get_current_rules_generation(project=self.project)
        standalone_generation = generation.get_current_rules_generation(
            task=self.standalone_task
        )

        self.assertTrue(task_generation.inherit)
        self.assertFalse(project_generation.inherit)
        self.assertFalse(standalone_generation.inherit)

        self.assertEqual(
            task_generation.source_settings_id, self.project_settings.id
        )
        self.assertEqual(
            project_generation.scope_settings_id, self.project_settings.id
        )
        self.assertEqual(
            standalone_generation.source_settings_id, self.standalone_settings.id
        )

        # Same effective rule content, different scope -> same fingerprint
        self.assertEqual(task_generation.fingerprint, project_generation.fingerprint)

        # Idempotent resolution
        self.assertEqual(
            generation.get_current_rules_generation(task=self.task).id,
            task_generation.id,
        )

    def test_different_rule_content_has_different_fingerprint(self):
        self.standalone_settings.requirements.filter(
            annotation_type=QualityRequirementAnnotationType.RECTANGLE
        ).update(enabled=True)

        standalone_generation = generation.get_current_rules_generation(
            task=self.standalone_task
        )
        project_generation = generation.get_current_rules_generation(project=self.project)
        self.assertNotEqual(
            standalone_generation.fingerprint, project_generation.fingerprint
        )

    def test_bump_rules_version_creates_new_generation(self):
        generation.bump_rules_version(self.project_settings)

        new_project_generation = generation.get_current_rules_generation(
            project=self.project
        )
        new_task_generation = generation.get_current_rules_generation(task=self.task)
        standalone_generation = generation.get_current_rules_generation(
            task=self.standalone_task
        )

        self.assertEqual(new_project_generation.source_rules_version, 2)

        self.assertEqual(
            new_task_generation.fingerprint, new_project_generation.fingerprint
        )

        # The standalone task generation is not affected by the project bump
        self.assertEqual(
            generation.get_current_rules_generation(task=self.standalone_task).id,
            standalone_generation.id,
        )

    def test_task_move_between_projects_bumps_settings_version(self):
        another_project = Project.objects.create(name="p2")
        another_settings = QualitySettings.objects.get(project=another_project)
        self.assertEqual(self.task_settings.rules_version, another_settings.rules_version)

        self.task.project = another_project
        self.task.save()

        self.task_settings.refresh_from_db()
        self.assertEqual(
            self.task_settings.rules_version, another_settings.rules_version + 1
        )
        # The moved task inherits the new project source
        moved_generation = generation.get_current_rules_generation(task=self.task)
        self.assertEqual(
            moved_generation.source_settings_id, another_settings.id
        )

        # Re-saving without a move does not bump
        version = self.task_settings.rules_version
        self.task.save()
        self.task_settings.refresh_from_db()
        self.assertEqual(self.task_settings.rules_version, version)

    def test_requirement_create_through_serializer_bumps_version(self):
        initial_version = self.standalone_settings.rules_version
        base_requirement = self.standalone_settings.requirements.get(
            annotation_type=QualityRequirementAnnotationType.RECTANGLE
        )
        serializer = QualityRequirementSerializer(
            data={
                "settings_id": self.standalone_settings.id,
                "name": "custom rect",
                "parent_requirement": base_requirement.id,
            },
            context={"request": None},
        )
        self.assertTrue(serializer.is_valid(raise_exception=True))
        requirement = serializer.save()
        self.assertIsInstance(requirement, QualityRequirement)

        self.standalone_settings.refresh_from_db()
        self.assertEqual(
            self.standalone_settings.rules_version, initial_version + 1
        )

    def test_is_rules_generation_current(self):
        current = generation.get_current_rules_generation(project=self.project)
        self.assertTrue(
            generation.is_rules_generation_current(current, project=self.project)
        )

        generation.bump_rules_version(self.project_settings)
        self.assertFalse(
            generation.is_rules_generation_current(current, project=self.project)
        )
        self.assertTrue(
            generation.is_rules_generation_current(
                generation.get_current_rules_generation(project=self.project),
                project=self.project,
            )
        )

    def test_status_enum_values(self):
        # Guard the status values used by all report-family logic
        self.assertEqual(QualityReportStatus.CURRENT.value, "current")
        self.assertEqual(QualityReportStatus.SUPERSEDED.value, "superseded")
