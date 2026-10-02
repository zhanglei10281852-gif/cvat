import pytest

import cvat.apps.quality_control.signals  # noqa: F401
from cvat.apps.engine.models import Job, JobType, Project, Segment, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import (
    QualityReport,
    QualityReportStatus,
    QualitySettings,
)
from cvat.apps.quality_control.report_families import (
    TaskReportSnapshot,
    publish_task_report_family,
)
from collections import Counter

from cvat.apps.quality_control.comparison_report import (
    ComparisonReport,
    ComparisonReportJobStats,
    ComparisonReportParameters,
    ComparisonReportSummary,
)
from cvat.apps.quality_control.serializers import (
    QualityReportListQuerySerializer,
    QualityReportSerializer,
)


def _comparison_report():
    return ComparisonReport(
        parameters=ComparisonReportParameters(inherited=True),
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


@pytest.mark.django_db
def test_report_serializer_status_and_filter():
    task = Task.objects.create(name="t")
    segment = Segment.objects.create(task=task, start_frame=0, stop_frame=1)
    gt = Job.objects.create(segment=segment, type=JobType.GROUND_TRUTH)
    job = Job.objects.create(segment=segment, type=JobType.ANNOTATION)
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
    family = publish_task_report_family(
        task=task,
        bound_generation=gen,
        snapshot=snapshot,
        task_comparison_report=_comparison_report(),
        job_comparison_reports={job.id: _comparison_report()},
    )
    data = QualityReportSerializer(family).data
    assert data["status"] == "current"
    assert data["generation_id"] == gen.id

    legacy = QualityReport.objects.create(
        task=task,
        target_last_updated=task.updated_date,
        gt_last_updated=gt.updated_date,
        data=_comparison_report().to_json(),
    )
    legacy_data = QualityReportSerializer(legacy).data
    assert legacy_data["status"] == "legacy"
    assert legacy_data["generation_id"] is None

    query = QualityReportListQuerySerializer(
        data={"status": ["current", "superseded"]}
    )
    assert query.is_valid(raise_exception=True)
    assert query.validated_data["status"] == ["current", "superseded"]

    current_rows = QualityReport.objects.filter(status=QualityReportStatus.CURRENT)
    assert family.id in current_rows.values_list("id", flat=True)
    assert set(current_rows.filter(task=task).values_list("id", flat=True)) == {family.id}
    legacy_rows = QualityReport.objects.filter(status__isnull=True)
    assert set(legacy_rows.values_list("id", flat=True)) == {legacy.id}
