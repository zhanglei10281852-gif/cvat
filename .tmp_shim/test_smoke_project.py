from collections import Counter

import pytest

import cvat.apps.quality_control.signals  # noqa: F401
from cvat.apps.engine.models import Job, JobType, Project, Segment, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.comparison_report import (
    ComparisonReport,
    ComparisonReportJobStats,
    ComparisonReportParameters,
    ComparisonReportSummary,
)
from cvat.apps.quality_control.models import QualityReport, QualityReportStatus
from cvat.apps.quality_control.quality_calculators import ProjectQualityCalculator
from cvat.apps.quality_control.report_families import (
    StaleGenerationError,
    TaskReportSnapshot,
    publish_project_report_family,
)


def _comparison_report(inherited=True):
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


def _make_project_task(project):
    task = Task.objects.create(name=f"t-{len(project.tasks.all())}", project=project)
    segment = Segment.objects.create(task=task, start_frame=0, stop_frame=1)
    gt = Job.objects.create(segment=segment, type=JobType.GROUND_TRUTH)
    job = Job.objects.create(segment=segment, type=JobType.ANNOTATION)
    return task, gt, job


def _publish_task_family(task, gt, job):
    gen = generation.get_current_rules_generation(task=task)
    snapshot = TaskReportSnapshot(
        generation_id=gen.id,
        target_last_updated=task.updated_date,
        gt_last_updated=gt.updated_date,
        job_ids=frozenset({job.id}),
        job_updated_dates={job.id: job.updated_date},
        assignee_ids={job.id: None},
        assignee_updated_dates={job.id: None},
    )
    from cvat.apps.quality_control.report_families import publish_task_report_family

    return publish_task_report_family(
        task=task,
        bound_generation=gen,
        snapshot=snapshot,
        task_comparison_report=_comparison_report(),
        job_comparison_reports={job.id: _comparison_report()},
    )


@pytest.mark.django_db
def test_project_publish_gate_and_idempotency():
    project = Project.objects.create(name="p")
    task, gt, job = _make_project_task(project)
    family = _publish_task_family(task, gt, job)
    gen = generation.get_current_rules_generation(project=project)

    report = ProjectQualityCalculator().compute_report(project)
    assert report.status == QualityReportStatus.CURRENT
    assert report.generation_id == gen.id
    assert set(report.children.values_list("id", flat=True)) == {family.id}

    # Recompute is idempotent
    again = ProjectQualityCalculator().compute_report(project)
    assert again.id == report.id

    # Stale project timestamp is rejected at publication
    project.touch()
    project.refresh_from_db()
    with pytest.raises(StaleGenerationError):
        publish_project_report_family(
            project=project,
            bound_generation=gen,
            snapshot=type(
                "S",
                (),
                {
                    "generation_id": gen.id,
                    "project_target_updated": report.target_last_updated,
                    "task_family_ids": frozenset({family.id}),
                },
            )(),
            project_comparison_report=_comparison_report(),
            task_families={task.id: family},
        )


@pytest.mark.django_db
def test_project_family_supersession_on_rules_change():
    project = Project.objects.create(name="p")
    task, gt, job = _make_project_task(project)
    first_family = _publish_task_family(task, gt, job)
    project_settings = project.quality_settings

    first_project = ProjectQualityCalculator().compute_report(project)
    assert set(first_project.children.values_list("id", flat=True)) == {first_family.id}

    # Rules change; a new task family is published under the new generation
    # (as the inline project recomputation would produce)
    generation.bump_rules_version(project_settings)
    project.touch()
    project.refresh_from_db()
    task.touch()
    task.refresh_from_db()
    gt.touch()
    gt.refresh_from_db()
    job.touch()
    job.refresh_from_db()
    second_family = _publish_task_family(task, gt, job)
    assert second_family.id != first_family.id
    assert second_family.generation.fingerprint == generation.get_current_rules_generation(
        project=project
    ).fingerprint

    second_project = ProjectQualityCalculator().compute_report(project)
    assert second_project.id != first_project.id
    assert second_project.status == QualityReportStatus.CURRENT
    first_project.refresh_from_db()
    assert first_project.status == QualityReportStatus.SUPERSEDED
    # Task family lifecycle is independent of the project aggregate
    assert QualityReport.objects.filter(task=task, status="current").count() == 1
    assert set(second_project.children.values_list("id", flat=True)) == {second_family.id}
