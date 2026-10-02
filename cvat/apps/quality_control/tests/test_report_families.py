# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import Counter

from django.test import TransactionTestCase

from cvat.apps.engine.models import Job, JobType, Project, Segment, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.comparison_report import (
    ComparisonReport,
    ComparisonReportJobStats,
    ComparisonReportParameters,
    ComparisonReportSummary,
)
from cvat.apps.quality_control.models import (
    QualityReport,
    QualityReportStatus,
)
from cvat.apps.quality_control.report_families import (
    ProjectReportSnapshot,
    StaleGenerationError,
    TaskReportSnapshot,
    publish_project_report_family,
    publish_task_report_family,
)


def _make_comparison_report(*, inherited: bool = True) -> ComparisonReport:
    return ComparisonReport(
        parameters=ComparisonReportParameters(inherited=inherited),
        comparison_summary=ComparisonReportSummary(
            frames=(),
            validation_frames=0,
            total_frames=0,
            conflict_count=0,
            error_count=0,
            conflicts_by_type=Counter(),
            tasks=None,
            jobs=ComparisonReportJobStats.create_empty(),
            requirements=None,
        ),
        groups={},
    )


def _make_task_with_jobs(name: str = "t", *, project: Project | None = None):
    task = Task.objects.create(name=name, project=project)
    segment = Segment.objects.create(task=task, start_frame=0, stop_frame=1)
    gt_job = Job.objects.create(segment=segment, type=JobType.GROUND_TRUTH)
    job = Job.objects.create(segment=segment, type=JobType.ANNOTATION)
    return task, gt_job, job


def _make_task_snapshot(task: Task, gt_job: Job, job: Job) -> TaskReportSnapshot:
    gen = generation.get_current_rules_generation(task=task)
    return gen, TaskReportSnapshot(
        generation_id=gen.id,
        target_last_updated=task.updated_date,
        gt_last_updated=gt_job.updated_date,
        job_ids=frozenset({job.id}),
        job_updated_dates={job.id: job.updated_date},
        assignee_ids={job.id: None},
        assignee_updated_dates={job.id: None},
    )


def _publish_task_family(task: Task, gt_job: Job, job: Job) -> QualityReport:
    gen, snapshot = _make_task_snapshot(task, gt_job, job)
    return publish_task_report_family(
        task=task,
        bound_generation=gen,
        snapshot=snapshot,
        task_comparison_report=_make_comparison_report(),
        job_comparison_reports={job.id: _make_comparison_report()},
    )


class TaskReportFamilyTestCase(TransactionTestCase):
    def test_publish_gate_rejects_stale_generation(self):
        task, gt_job, job = _make_task_with_jobs()
        gen, snapshot = _make_task_snapshot(task, gt_job, job)

        generation.bump_rules_version(task.quality_settings)

        with self.assertRaises(StaleGenerationError):
            publish_task_report_family(
                task=task,
                bound_generation=gen,
                snapshot=snapshot,
                task_comparison_report=_make_comparison_report(),
                job_comparison_reports={job.id: _make_comparison_report()},
            )

    def test_publish_gate_rejects_stale_timestamps(self):
        task, gt_job, job = _make_task_with_jobs()
        gen, snapshot = _make_task_snapshot(task, gt_job, job)

        # A stale annotation snapshot
        task.touch()
        task.refresh_from_db()
        with self.assertRaises(StaleGenerationError):
            publish_task_report_family(
                task=task,
                bound_generation=gen,
                snapshot=snapshot,
                task_comparison_report=_make_comparison_report(),
                job_comparison_reports={job.id: _make_comparison_report()},
            )

        # A stale GT snapshot
        task2, gt2, job2 = _make_task_with_jobs("t2")
        gen2, snapshot2 = _make_task_snapshot(task2, gt2, job2)
        gt2.touch()
        gt2.refresh_from_db()
        with self.assertRaises(StaleGenerationError):
            publish_task_report_family(
                task=task2,
                bound_generation=gen2,
                snapshot=snapshot2,
                task_comparison_report=_make_comparison_report(),
                job_comparison_reports={job2.id: _make_comparison_report()},
            )

    def test_idempotent_publish_does_not_duplicate_family(self):
        task, gt_job, job = _make_task_with_jobs()
        first = _publish_task_family(task, gt_job, job)

        second = _publish_task_family(task, gt_job, job)
        self.assertEqual(second.id, first.id)
        self.assertEqual(
            QualityReport.objects.filter(task=task, status=QualityReportStatus.CURRENT).count(),
            1,
        )
        self.assertEqual(
            QualityReport.objects.filter(job=job, status=QualityReportStatus.CURRENT).count(),
            1,
        )
        self.assertEqual(QualityReport.objects.count(), 2)  # task root + job report

    def test_assignee_change_supersedes_whole_family(self):
        import dataclasses

        from django.utils import timezone

        task, gt_job, job = _make_task_with_jobs()

        def publish_with_current_assignees() -> QualityReport:
            # The shared helper hardcodes empty assignee state; rebuild that
            # part of the snapshot from the actual job rows.
            gen, snapshot = _make_task_snapshot(task, gt_job, job)
            snapshot = dataclasses.replace(
                snapshot,
                assignee_ids={job.id: job.assignee_id},
                assignee_updated_dates={job.id: job.assignee_updated_date},
            )
            return publish_task_report_family(
                task=task,
                bound_generation=gen,
                snapshot=snapshot,
                task_comparison_report=_make_comparison_report(),
                job_comparison_reports={job.id: _make_comparison_report()},
            )

        first = publish_with_current_assignees()

        # A pure job assignee change does not bump the task timestamp, but it
        # must still invalidate the family (assignees are report metadata and
        # may participate in the quality job filter).
        Job.objects.filter(id=job.id).update(
            assignee_updated_date=timezone.now()
        )
        job.refresh_from_db()

        second = publish_with_current_assignees()
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.status, QualityReportStatus.CURRENT)
        first.refresh_from_db()
        self.assertEqual(first.status, QualityReportStatus.SUPERSEDED)
        self.assertEqual(
            set(
                first.children.values_list("status", flat=True)
            ),
            {QualityReportStatus.SUPERSEDED},
        )

    def test_data_change_supersedes_whole_family(self):
        task, gt_job, job = _make_task_with_jobs()
        first = _publish_task_family(task, gt_job, job)

        task.touch()
        task.refresh_from_db()
        job.touch()
        job.refresh_from_db()
        second = _publish_task_family(task, gt_job, job)

        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.status, QualityReportStatus.CURRENT)
        first.refresh_from_db()
        self.assertEqual(first.status, QualityReportStatus.SUPERSEDED)
        self.assertEqual(
            set(
                first.children.values_list("status", flat=True)
            ),
            {QualityReportStatus.SUPERSEDED},
        )
        self.assertEqual(
            QualityReport.objects.filter(task=task, status=QualityReportStatus.CURRENT).count(),
            1,
        )
        self.assertEqual(
            QualityReport.objects.filter(job=job, status=QualityReportStatus.CURRENT).count(),
            1,
        )
        self.assertEqual(first.generation_id, second.generation_id)


class ProjectReportFamilyTestCase(TransactionTestCase):
    def test_project_family_publish_idempotency_and_supersession(self):
        project = Project.objects.create(name="p")
        task, gt_job, job = _make_task_with_jobs("t", project=project)
        task_family = _publish_task_family(task, gt_job, job)
        project_generation = generation.get_current_rules_generation(project=project)

        project_report = QualityReport(
            project=project,
            target_last_updated=project.updated_date,
            gt_last_updated=None,
            data=_make_comparison_report(inherited=False).to_json(),
        )

        snapshot = ProjectReportSnapshot(
            generation_id=project_generation.id,
            project_target_updated=project.updated_date,
            task_family_ids=frozenset({task_family.id}),
        )

        first = publish_project_report_family(
            project=project,
            bound_generation=project_generation,
            snapshot=snapshot,
            project_comparison_report=_make_comparison_report(inherited=False),
            task_families={task.id: task_family},
        )
        self.assertEqual(first.status, QualityReportStatus.CURRENT)
        self.assertEqual(
            set(first.children.values_list("id", flat=True)), {task_family.id}
        )

        # Same aggregate is idempotent
        again = publish_project_report_family(
            project=project,
            bound_generation=project_generation,
            snapshot=snapshot,
            project_comparison_report=_make_comparison_report(inherited=False),
            task_families={task.id: task_family},
        )
        self.assertEqual(again.id, first.id)

        # Stale project snapshot is rejected
        project.touch()
        project.refresh_from_db()
        with self.assertRaises(StaleGenerationError):
            publish_project_report_family(
                project=project,
                bound_generation=project_generation,
                snapshot=snapshot,
                project_comparison_report=_make_comparison_report(inherited=False),
                task_families={task.id: task_family},
            )

        # A new project family supersedes only the project root; task families
        # keep their own lifecycle.
        new_snapshot = ProjectReportSnapshot(
            generation_id=project_generation.id,
            project_target_updated=project.updated_date,
            task_family_ids=frozenset({task_family.id}),
        )
        second = publish_project_report_family(
            project=project,
            bound_generation=project_generation,
            snapshot=new_snapshot,
            project_comparison_report=_make_comparison_report(inherited=False),
            task_families={task.id: task_family},
        )
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.status, QualityReportStatus.CURRENT)
        first.refresh_from_db()
        self.assertEqual(first.status, QualityReportStatus.SUPERSEDED)
        task_family.refresh_from_db()
        self.assertEqual(task_family.status, QualityReportStatus.CURRENT)
        self.assertEqual(
            QualityReport.objects.filter(
                project=project, status=QualityReportStatus.CURRENT
            ).count(),
            1,
        )

    def test_project_publish_rejects_changed_task_family_set(self):
        project = Project.objects.create(name="p")
        task, gt_job, job = _make_task_with_jobs("t", project=project)
        first_family = _publish_task_family(task, gt_job, job)
        project_generation = generation.get_current_rules_generation(project=project)

        # Publish a newer task family
        task.touch()
        task.refresh_from_db()
        job.touch()
        job.refresh_from_db()
        second_family = _publish_task_family(task, gt_job, job)
        self.assertNotEqual(second_family.id, first_family.id)

        snapshot = ProjectReportSnapshot(
            generation_id=project_generation.id,
            project_target_updated=project.updated_date,
            task_family_ids=frozenset({first_family.id}),
        )
        # The stale family id fails the publication gate
        with self.assertRaises(StaleGenerationError):
            publish_project_report_family(
                project=project,
                bound_generation=project_generation,
                snapshot=snapshot,
                project_comparison_report=_make_comparison_report(inherited=False),
                task_families={task.id: first_family},
            )

    def test_project_publish_rejects_family_with_stale_ground_truth(self):
        project = Project.objects.create(name="p")
        task, gt_job, job = _make_task_with_jobs("t", project=project)
        task_family = _publish_task_family(task, gt_job, job)
        project_generation = generation.get_current_rules_generation(project=project)

        # The family stays "current", but the ground truth it was computed
        # against changed while the project aggregate was being assembled.
        gt_job.touch()
        gt_job.refresh_from_db()

        snapshot = ProjectReportSnapshot(
            generation_id=project_generation.id,
            project_target_updated=project.updated_date,
            task_family_ids=frozenset({task_family.id}),
        )
        with self.assertRaises(StaleGenerationError) as catcher:
            publish_project_report_family(
                project=project,
                bound_generation=project_generation,
                snapshot=snapshot,
                project_comparison_report=_make_comparison_report(inherited=False),
                task_families={task.id: task_family},
            )
        self.assertEqual(catcher.exception.reason, "task_family_gt_updated")
        # Nothing was published as current for the project
        self.assertIsNone(
            QualityReport.objects.filter(
                project=project, status=QualityReportStatus.CURRENT
            ).first()
        )

    def test_task_publish_rejects_removed_ground_truth(self):
        task, gt_job, job = _make_task_with_jobs()
        gen, snapshot = _make_task_snapshot(task, gt_job, job)

        # The ground truth job disappears while the worker is computing.
        gt_job.segment.delete()

        with self.assertRaises(StaleGenerationError) as catcher:
            publish_task_report_family(
                task=task,
                bound_generation=gen,
                snapshot=snapshot,
                task_comparison_report=_make_comparison_report(),
                job_comparison_reports={job.id: _make_comparison_report()},
            )
        self.assertEqual(catcher.exception.reason, "gt_updated")
