# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db import transaction

from cvat.apps.engine.log import ServerLogManager
from cvat.apps.quality_control.generation import get_current_rules_generation
from cvat.apps.quality_control.models import (
    AnnotationConflict,
    AnnotationId,
    QualityReport,
    QualityReportStatus,
    QualityRulesGeneration,
)
from cvat.utils import django_database as db_utils

if TYPE_CHECKING:
    from cvat.apps.engine.models import Project
    from cvat.apps.quality_control.comparison_report import ComparisonReport

slogger = ServerLogManager("quality")

# Maximum number of times a worker recomputes a report when the bound
# generation/data snapshot becomes stale before it discards the result.
MAX_STALE_RECOMPUTES = 2


class StaleGenerationError(Exception):
    """Raised at publication when the bound snapshot is no longer current."""

    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


@dataclass(frozen=True)
class TaskReportSnapshot:
    generation_id: int
    target_last_updated: datetime
    gt_last_updated: datetime | None
    job_ids: frozenset[int]
    job_updated_dates: dict[int, datetime]
    assignee_ids: dict[int, int | None]
    assignee_updated_dates: dict[int, datetime | None]


@dataclass(frozen=True)
class ProjectReportSnapshot:
    generation_id: int
    project_target_updated: datetime
    task_family_ids: frozenset[int]


def get_current_task_report(task_id: int) -> QualityReport | None:
    return (
        QualityReport.objects.filter(task_id=task_id, status=QualityReportStatus.CURRENT)
        .order_by("-id")
        .first()
    )


def get_current_project_report(project_id: int) -> QualityReport | None:
    return (
        QualityReport.objects.filter(
            project_id=project_id, status=QualityReportStatus.CURRENT
        )
        .order_by("-id")
        .first()
    )


def publish_project_report_family(
    *,
    project: Project,
    bound_generation: QualityRulesGeneration,
    snapshot: ProjectReportSnapshot,
    project_comparison_report: ComparisonReport,
    task_families: dict[int, QualityReport],
) -> QualityReport:
    """
    Publish a project report current family. The project aggregate itself does
    not own conflicts; the linked task families provide them. The publication
    atomically verifies that the project target and the selected task families
    did not change during aggregation.
    """
    from cvat.apps.engine.models import (
        Job,
        JobType,
        Project as ProjectModel,
        Task,
    )

    with transaction.atomic():
        locked_project = ProjectModel.objects.select_for_update().get(pk=project.pk)
        current_generation = get_current_rules_generation(project=locked_project)
        if current_generation.id != bound_generation.id:
            raise StaleGenerationError(
                "project_rules_generation",
                bound_generation_id=bound_generation.id,
                current_generation_id=current_generation.id,
            )

        if locked_project.updated_date != snapshot.project_target_updated:
            raise StaleGenerationError(
                "project_target_updated",
                snapshot_value=snapshot.project_target_updated.isoformat(),
                current_value=locked_project.updated_date.isoformat(),
            )

        expected_family_ids = set(snapshot.task_family_ids)

        # Resolve backing tasks before taking any report row lock. The family
        # id -> task id mapping is immutable once a report is created, so a
        # plain read is enough to establish the lock order.
        family_task_map = dict(
            QualityReport.objects.filter(id__in=expected_family_ids).values_list(
                "id", "task_id"
            )
        )
        if set(family_task_map) != expected_family_ids or any(
            task_id is None for task_id in family_task_map.values()
        ):
            raise StaleGenerationError(
                "task_families",
                expected_ids=sorted(expected_family_ids),
                current_ids=sorted(family_task_map),
            )

        task_ids = sorted(set(family_task_map.values()))

        # Lock backing tasks and their jobs BEFORE the family report rows, so
        # the lock order (project -> task -> jobs -> reports) matches
        # publish_task_report_family (task -> jobs -> reports) and cannot
        # deadlock against a concurrent task family publication.
        locked_tasks = {
            locked_task.id: locked_task
            for locked_task in (
                Task.objects.select_for_update().filter(id__in=task_ids).order_by("id")
            )
        }
        if set(locked_tasks) != set(task_ids):
            raise StaleGenerationError(
                "task_families",
                expected_ids=sorted(expected_family_ids),
                current_ids=sorted(family_task_map),
            )

        locked_gt_jobs = {
            gt_job.segment.task_id: gt_job
            for gt_job in (
                Job.objects.select_for_update()
                .filter(segment__task_id__in=task_ids, type=JobType.GROUND_TRUTH)
                .order_by("id")
            )
        }

        # Snapshot the family child job reports (immutable values, but only
        # meaningful for current roots) to learn which jobs have to be locked.
        family_child_rows: dict[int, list[dict]] = defaultdict(list)
        for child_row in (
            QualityReport.objects.filter(
                parents__in=expected_family_ids, job__isnull=False
            ).values(
                "parents",
                "job_id",
                "target_last_updated",
                "assignee_id",
                "assignee_last_updated",
            )
        ):
            family_child_rows[child_row["parents"]].append(child_row)

        covered_job_ids = {
            child_row["job_id"]
            for child_rows in family_child_rows.values()
            for child_row in child_rows
        }
        locked_jobs = {
            locked_job.id: locked_job
            for locked_job in (
                Job.objects.select_for_update()
                .filter(id__in=covered_job_ids)
                .order_by("id")
            )
        }

        # Only now lock the family report rows themselves and verify they are
        # still the single current family of their tasks.
        selected_families = list(
            QualityReport.objects.select_for_update()
            .filter(
                id__in=expected_family_ids,
                task__project=locked_project,
                status=QualityReportStatus.CURRENT,
            )
            .order_by("id")
        )
        selected_ids = {family.id for family in selected_families}
        if selected_ids != expected_family_ids:
            raise StaleGenerationError(
                "task_families",
                expected_ids=sorted(expected_family_ids),
                current_ids=sorted(selected_ids),
            )

        for family in selected_families:
            if family.generation_id is not None and (
                family.generation.fingerprint != bound_generation.fingerprint
                and family.parameters.inherited
            ):
                raise StaleGenerationError(
                    "task_family_generation",
                    task_family_id=family.id,
                )

            # The family set and fingerprints may match while the underlying
            # task annotations, ground truth or job assignees changed after
            # the aggregator selected this family. Reject the aggregate so the
            # worker recomputes instead of publishing a mixed snapshot.
            locked_task = locked_tasks[family.task_id]
            if family.target_last_updated != locked_task.updated_date:
                raise StaleGenerationError(
                    "task_family_target_updated",
                    task_family_id=family.id,
                )

            locked_gt_job = locked_gt_jobs.get(family.task_id)
            current_gt_updated = (
                locked_gt_job.updated_date if locked_gt_job is not None else None
            )
            if (family.gt_last_updated or None) != (current_gt_updated or None):
                raise StaleGenerationError(
                    "task_family_gt_updated",
                    task_family_id=family.id,
                )

            for child_row in family_child_rows.get(family.id, ()):
                locked_job = locked_jobs.get(child_row["job_id"])
                if locked_job is None:
                    raise StaleGenerationError(
                        "task_family_job_removed",
                        task_family_id=family.id,
                        job_id=child_row["job_id"],
                    )
                if child_row["target_last_updated"] != locked_job.updated_date:
                    raise StaleGenerationError(
                        "task_family_job_updated",
                        task_family_id=family.id,
                        job_id=locked_job.id,
                    )
                if child_row["assignee_id"] != locked_job.assignee_id:
                    raise StaleGenerationError(
                        "task_family_job_assignee",
                        task_family_id=family.id,
                        job_id=locked_job.id,
                    )
                if (child_row["assignee_last_updated"] or None) != (
                    locked_job.assignee_updated_date or None
                ):
                    raise StaleGenerationError(
                        "task_family_job_assignee_updated",
                        task_family_id=family.id,
                        job_id=locked_job.id,
                    )

        existing = (
            QualityReport.objects.select_for_update()
            .filter(project=locked_project, status=QualityReportStatus.CURRENT)
            .order_by("-id")
            .first()
        )
        if existing is not None:
            existing_family_ids = set(
                existing.children.filter(task__project=locked_project).values_list(
                    "id", flat=True
                )
            )
            if (
                existing.target_last_updated == snapshot.project_target_updated
                and existing_family_ids == expected_family_ids
            ):
                return existing

            existing.status = QualityReportStatus.SUPERSEDED
            existing.save(update_fields=["status"])

        project_report = QualityReport(
            project=locked_project,
            generation=bound_generation,
            status=QualityReportStatus.CURRENT,
            target_last_updated=snapshot.project_target_updated,
            gt_last_updated=None,
            data=project_comparison_report.to_json(),
        )
        project_report.save()
        project_report.children.add(*selected_families)
        return project_report


def get_current_job_report(job_id: int) -> QualityReport | None:
    return (
        QualityReport.objects.filter(job_id=job_id, status=QualityReportStatus.CURRENT)
        .order_by("-id")
        .first()
    )


def _same_timestamp(left: datetime | None, right: datetime | None) -> bool:
    return left == right


def _snapshot_matches_current(
    snapshot: TaskReportSnapshot,
    *,
    bound_generation: QualityRulesGeneration,
    task: Task,
    jobs: dict[int, Job],
    gt_job: Job | None,
    current_generation: QualityRulesGeneration,
) -> None:
    if current_generation.id != bound_generation.id:
        raise StaleGenerationError(
            "rules_generation",
            bound_generation_id=bound_generation.id,
            current_generation_id=current_generation.id,
        )

    if task.updated_date != snapshot.target_last_updated:
        raise StaleGenerationError(
            "target_updated",
            snapshot_value=snapshot.target_last_updated.isoformat(),
            current_value=task.updated_date.isoformat(),
        )

    # The ground truth job is not part of snapshot.job_ids, hence it is not
    # covered by the per-job checks below. It may have been touched, removed or
    # added while the report was being computed, in which case every comparison
    # result in this snapshot would describe a mixed generation.
    current_gt_updated = gt_job.updated_date if gt_job is not None else None
    if not _same_timestamp(current_gt_updated, snapshot.gt_last_updated):
        raise StaleGenerationError(
            "gt_updated",
            snapshot_value=(
                snapshot.gt_last_updated.isoformat()
                if snapshot.gt_last_updated
                else None
            ),
            current_value=current_gt_updated.isoformat() if current_gt_updated else None,
        )

    for job_id, job in jobs.items():
        expected_updated = snapshot.job_updated_dates.get(job_id)
        if expected_updated is None or job.updated_date != expected_updated:
            raise StaleGenerationError(
                "job_updated",
                job_id=job_id,
                snapshot_value=expected_updated.isoformat() if expected_updated else None,
                current_value=job.updated_date.isoformat(),
            )

        expected_assignee = snapshot.assignee_ids.get(job_id)
        expected_assignee_updated = snapshot.assignee_updated_dates.get(job_id)
        if job.assignee_id != expected_assignee:
            raise StaleGenerationError(
                "job_assignee",
                job_id=job_id,
                snapshot_value=expected_assignee,
                current_value=job.assignee_id,
            )
        if not _same_timestamp(job.assignee_updated_date, expected_assignee_updated):
            raise StaleGenerationError(
                "job_assignee_updated",
                job_id=job_id,
                snapshot_value=(
                    expected_assignee_updated.isoformat()
                    if expected_assignee_updated
                    else None
                ),
                current_value=(
                    job.assignee_updated_date.isoformat()
                    if job.assignee_updated_date
                    else None
                ),
            )


def _save_conflicts(
    db_job_reports: dict[int, QualityReport],
    job_comparison_reports: dict[int, ComparisonReport],
) -> None:
    db_conflicts: list[AnnotationConflict] = []
    for job_id, comparison_report in job_comparison_reports.items():
        db_job_report = db_job_reports[job_id]
        for conflict in comparison_report.get_conflicts():
            db_conflicts.append(
                AnnotationConflict(
                    type=conflict.type,
                    frame=conflict.frame,
                    severity=conflict.severity,
                    report=db_job_report,
                )
            )

    db_utils.bulk_create(AnnotationConflict, db_conflicts)

    db_conflicts_iter = iter(db_conflicts)
    for job_id, comparison_report in job_comparison_reports.items():
        for conflict in comparison_report.get_conflicts():
            db_conflict = next(db_conflicts_iter)
            for ann_id in conflict.annotation_ids:
                AnnotationId.objects.create(
                    obj_id=ann_id["obj_id"],
                    job_id=ann_id["job_id"],
                    type=ann_id["type"],
                    shape_type=ann_id["shape_type"],
                    conflict=db_conflict,
                )


def _supersede_previous_family(previous: QualityReport | None) -> None:
    if previous is None:
        return

    child_ids = list(previous.children.values_list("id", flat=True))
    family_ids = [previous.id, *child_ids]
    QualityReport.objects.filter(id__in=family_ids).update(
        status=QualityReportStatus.SUPERSEDED
    )


def _family_children_match_jobs(
    family: QualityReport,
    expected_jobs: dict[int, tuple[datetime, int | None, datetime | None]],
) -> bool:
    """
    Check that the family job reports still describe exactly ``expected_jobs``
    with identical update and assignee timestamps. This covers changes that do
    not bump the task ``updated_date`` - in particular job reassignment, which
    can also change the set of jobs matched by an assignee-based job filter.
    """
    children = {
        child["job_id"]: child
        for child in family.children.filter(job__isnull=False).values(
            "job_id",
            "target_last_updated",
            "assignee_id",
            "assignee_last_updated",
        )
    }
    if set(children) != set(expected_jobs):
        return False

    for job_id, (updated_date, assignee_id, assignee_updated_date) in expected_jobs.items():
        child = children[job_id]
        if child["target_last_updated"] != updated_date:
            return False
        if child["assignee_id"] != assignee_id:
            return False
        if (child["assignee_last_updated"] or None) != (assignee_updated_date or None):
            return False

    return True


def publish_task_report_family(
    *,
    task: Task,
    bound_generation: QualityRulesGeneration,
    snapshot: TaskReportSnapshot,
    task_comparison_report: ComparisonReport,
    job_comparison_reports: dict[int, ComparisonReport],
) -> QualityReport:
    """
    Atomically validate the report snapshot and publish it as the single
    current report family. Raises StaleGenerationError when the bound rules
    generation or the captured data timestamps are no longer current.
    Idempotently returns the existing current family when nothing changed.
    """
    from cvat.apps.engine.models import Job, JobType

    with transaction.atomic():
        locked_task = task.__class__.objects.select_for_update().get(pk=task.pk)
        locked_jobs = {
            job.id: job
            for job in Job.objects.select_for_update()
            .filter(pk__in=snapshot.job_ids)
            .select_related("segment")
        }
        locked_gt_job = (
            Job.objects.select_for_update()
            .filter(segment__task_id=locked_task.pk, type=JobType.GROUND_TRUTH)
            .first()
        )

        current_generation = get_current_rules_generation(task=locked_task)
        _snapshot_matches_current(
            snapshot,
            bound_generation=bound_generation,
            task=locked_task,
            jobs=locked_jobs,
            gt_job=locked_gt_job,
            current_generation=current_generation,
        )

        existing = (
            QualityReport.objects.select_for_update()
            .filter(task=locked_task, status=QualityReportStatus.CURRENT)
            .order_by("-id")
            .first()
        )
        snapshot_jobs = {
            job_id: (
                snapshot.job_updated_dates[job_id],
                snapshot.assignee_ids[job_id],
                snapshot.assignee_updated_dates[job_id],
            )
            for job_id in snapshot.job_ids
        }
        if existing is not None:
            # Same rules and the same task, ground truth and per-job snapshots:
            # the duplicate request is idempotently served by the existing
            # current family. Per-job checks are required because job
            # reassignment does not bump the task's updated_date.
            if (
                existing.target_last_updated == snapshot.target_last_updated
                and (existing.gt_last_updated or None) == (
                    snapshot.gt_last_updated or None
                )
                and _family_children_match_jobs(existing, snapshot_jobs)
            ):
                return existing

            _supersede_previous_family(existing)

        db_task_report = QualityReport(
            task=locked_task,
            generation=bound_generation,
            status=QualityReportStatus.CURRENT,
            target_last_updated=snapshot.target_last_updated,
            gt_last_updated=snapshot.gt_last_updated,
            assignee_id=locked_task.assignee_id,
            assignee_last_updated=locked_task.assignee_updated_date,
            data=task_comparison_report.to_json(),
        )
        db_task_report.save()

        db_job_reports: dict[int, QualityReport] = {}
        for job_id, comparison_report in job_comparison_reports.items():
            locked_job = locked_jobs[job_id]
            db_job_report = QualityReport(
                job=locked_job,
                generation=bound_generation,
                status=QualityReportStatus.CURRENT,
                target_last_updated=snapshot.job_updated_dates[job_id],
                gt_last_updated=None,
                assignee_id=locked_job.assignee_id,
                assignee_last_updated=locked_job.assignee_updated_date,
                data=comparison_report.to_json(),
            )
            db_job_reports[job_id] = db_job_report

        db_utils.bulk_create(QualityReport, list(db_job_reports.values()))

        _save_conflicts(db_job_reports, job_comparison_reports)

        db_task_report.children.add(*db_job_reports.values())
        return db_task_report
