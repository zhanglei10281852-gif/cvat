import datetime

import pytest

from cvat.apps.engine.models import Job, JobType, Project, Segment, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.comparison_report import (
    ComparisonParameters,
    ComparisonReport,
    ComparisonReportSummary,
)
from cvat.apps.quality_control.models import (
    QualityReport,
    QualityReportStatus,
    QualitySettings,
)
from cvat.apps.quality_control.report_families import (
    StaleGenerationError,
    TaskReportSnapshot,
    publish_task_report_family,
)


def _make_task_with_jobs(name="t"):
    task = Task.objects.create(name=name)
    settings = QualitySettings.objects.get(task=task)  # created by the signal
    segment = Segment.objects.create(task=task, start_frame=0, stop_frame=1)
    gt = Job.objects.create(segment=segment, type=JobType.GROUND_TRUTH)
    job = Job.objects.create(segment=segment, type=JobType.ANNOTATION)
    return task, gt, job


def _comparison_report():
    from collections import Counter

    return ComparisonReport(
        parameters=ComparisonParameters(),
        comparison_summary=ComparisonReportSummary(
            frames=(),
            validation_frames=0,
            total_frames=0,
            conflict_count=0,
            error_count=0,
            conflicts_by_type=Counter(),
            tasks=None,
            jobs=None,
            requirements=None,
        ),
        groups={},
    )


def _snapshot(task, gt, job, gen):
    return TaskReportSnapshot(
        generation_id=gen.id,
        target_last_updated=task.updated_date,
        gt_last_updated=gt.updated_date,
        job_ids=frozenset({job.id}),
        job_updated_dates={job.id: job.updated_date},
        assignee_ids={job.id: None},
        assignee_updated_dates={job.id: None},
    )


def _publish(task, gt, job, gen, task_report=None, job_reports=None):
    return publish_task_report_family(
        task=task,
        bound_generation=gen,
        snapshot=_snapshot(task, gt, job, gen),
        task_comparison_report=task_report or _comparison_report(),
        job_comparison_reports=job_reports or {job.id: _comparison_report()},
    )


@pytest.mark.django_db
def test_publish_gates_on_generation_and_data():
    task, gt, job = _make_task_with_jobs()
    gen = generation.get_current_rules_generation(task=task)

    # Stale bound generation
    generation.bump_rules_version(QualitySettings.objects.get(task=task))
    current_gen = generation.get_current_rules_generation(task=task)
    with pytest.raises(StaleGenerationError):
        _publish(task, gt, job, gen)

    # Stale task timestamp (annotation change)
    task.touch()
    task.refresh_from_db()
    stale_snapshot = TaskReportSnapshot(
        generation_id=current_gen.id,
        target_last_updated=task.updated_date - datetime.timedelta(seconds=1),
        gt_last_updated=gt.updated_date,
        job_ids=frozenset({job.id}),
        job_updated_dates={job.id: job.updated_date},
        assignee_ids={job.id: None},
        assignee_updated_dates={job.id: None},
    )
    with pytest.raises(StaleGenerationError):
        publish_task_report_family(
            task=task,
            bound_generation=current_gen,
            snapshot=stale_snapshot,
            task_comparison_report=_comparison_report(),
            job_comparison_reports={job.id: _comparison_report()},
        )

    # Stale GT timestamp
    gt.touch()
    gt.refresh_from_db()
    with pytest.raises(StaleGenerationError):
        _publish(task, gt, job, current_gen)


@pytest.mark.django_db
def test_idempotent_family_and_supersession():
    task, gt, job = _make_task_with_jobs()
    gen = generation.get_current_rules_generation(task=task)

    first = _publish(task, gt, job, gen)
    assert first.status == QualityReportStatus.CURRENT
    assert first.generation_id == gen.id
    assert set(first.children.values_list("id", flat=True)) == set(
        QualityReport.objects.filter(job=job).values_list("id", flat=True)
    )
    assert QualityReport.objects.filter(task=task, status="current").count() == 1
    assert QualityReport.objects.filter(job=job, status="current").count() == 1

    # Identical snapshot is idempotent
    again = _publish(task, gt, job, gen)
    assert again.id == first.id
    assert QualityReport.objects.count() == 2  # the task root + its job report
    assert QualityReport.objects.filter(task=task).count() == 1

    # Data change publishes a new family and supersedes the old one as a whole
    task.touch()
    task.refresh_from_db()
    job.touch()
    job.refresh_from_db()
    second = _publish(task, gt, job, gen)
    assert second.id != first.id
    assert second.status == QualityReportStatus.CURRENT
    first.refresh_from_db()
    assert first.status == QualityReportStatus.SUPERSEDED
    assert all(
        status == QualityReportStatus.SUPERSEDED
        for status in first.children.values_list("status", flat=True)
    )
    assert QualityReport.objects.filter(task=task, status="current").count() == 1
    assert QualityReport.objects.filter(job=job, status="current").count() == 1
    assert QualityReport.objects.filter(task=task, status="superseded").count() == 1
    assert QualityReport.objects.filter(job=job, status="superseded").count() == 1
