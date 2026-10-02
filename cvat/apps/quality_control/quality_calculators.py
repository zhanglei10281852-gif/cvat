# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import Counter
from contextlib import suppress
from copy import deepcopy
from datetime import datetime

from cvat.apps.engine.filters import JsonLogicFilter
from cvat.apps.engine.log import ServerLogManager
from cvat.apps.engine.media_io.frame_provider import TaskFrameProvider
from cvat.apps.engine.models import (
    Image,
    Job,
    JobType,
    Project,
    Task,
    ValidationMode,
)
from cvat.apps.engine.utils import take_by
from cvat.apps.quality_control import models
from cvat.apps.quality_control.comparison_report import (
    AnnotationConflict,
    ComparisonReport,
    ComparisonReportAnnotationsSummary,
    ComparisonReportFrameComparisonSummary,
    ComparisonReportJobStats,
    ComparisonReportParameters,
    ComparisonReportRequirementCalculation,
    ComparisonReportRequirementSummary,
    ComparisonReportSummary,
    ComparisonReportTaskStats,
    deduplicate_annotation_conflicts,
)
from cvat.apps.quality_control.data_providers import JobDataProvider, QualitySettingsManager
from cvat.apps.quality_control.generation import get_current_rules_generation
from cvat.apps.quality_control.quality_handlers import (
    DatasetQualityEstimator,
    EffectiveQualityRequirement,
    build_requirement_comparison_summary,
    build_requirement_report,
    build_requirements_summary,
    merge_frame_summaries,
    resolve_effective_requirements,
    select_requirement_calculation,
)
from cvat.apps.quality_control.report_families import (
    MAX_STALE_RECOMPUTES,
    ProjectReportSnapshot,
    StaleGenerationError,
    TaskReportSnapshot,
    get_current_project_report,
    get_current_task_report,
    publish_project_report_family,
    publish_task_report_family,
)
from cvat.utils import django_database as db_utils

_DEFAULT_FETCH_CHUNK_SIZE = 1000


def _all_enabled_requirements_completed(summary: ComparisonReportSummary) -> bool:
    requirements = summary.requirements
    return bool(
        summary.validation_frames
        and requirements
        and requirements.enabled_count
        and requirements.completed_count == requirements.enabled_count
    )


class TaskQualityCalculator:
    # JSON filter lookups
    JOB_FILTER_LOOKUPS = {
        "id": "id",
        "type": "type",
        "state": "state",
        "stage": "stage",
        "assignee": "assignee__username",
        "task_id": "segment__task__id",
        "task_name": "segment__task__name",
    }

    def compute_report(
        self,
        task: Task | int,
        *,
        generation_id: int | None = None,
    ) -> models.QualityReport | None:
        if isinstance(task, int):
            task = Task.objects.get(id=task)

        # Bound rules generation; a stale snapshot is recomputed under the
        # current generation and, if the rules keep changing, is discarded.
        bound_generation_id = generation_id
        for _attempt in range(MAX_STALE_RECOMPUTES + 1):
            snapshot_outputs = self._compute_task_report_snapshot(
                task, generation_id=bound_generation_id
            )
            if snapshot_outputs is None:
                # The GT job was removed while the request was queued
                return None

            try:
                return publish_task_report_family(**snapshot_outputs)
            except StaleGenerationError as stale_error:
                ServerLogManager("quality").glob.warning(
                    "Stale quality report snapshot for task id %s, recomputing "
                    "(attempt %s/%s): %s %s",
                    task.id,
                    _attempt + 1,
                    MAX_STALE_RECOMPUTES + 1,
                    stale_error.reason,
                    stale_error.details,
                )
                # Rebind to the latest generation on the following snapshot
                bound_generation_id = None
                continue

        ServerLogManager("quality").glob.warning(
            "Discarding stale quality report computation for task id %s: "
            "the rules/data generation kept changing; returning the current report",
            task.id,
        )
        return get_current_task_report(task.id)

    def _compute_task_report_snapshot(
        self,
        task: Task,
        *,
        generation_id: int | None,
    ) -> dict | None:
        # Resolve the bound generation before opening the READ ONLY
        # repeatable-read transaction: after a stale recompute the current
        # generation row may not exist yet and resolving it lazily would have
        # to INSERT, which a read-only transaction rejects on PostgreSQL.
        # Re-read the task so a project move between retries cannot make the
        # generation resolve against a stale inheritance source.
        resolution_task = Task.objects.only("id", "project_id").get(id=task.id)
        bound_generation = (
            models.QualityRulesGeneration.objects.get(id=generation_id)
            if generation_id is not None
            else get_current_rules_generation(task=resolution_task)
        )

        with db_utils.transaction_with_repeatable_read():
            task = Task.objects.select_related("data", "project").get(id=task.id)

            # The GT job could have been removed during scheduling, so we need to check it.
            gt_job_id = (
                Job.objects.filter(
                    segment__task=task,
                    type=JobType.GROUND_TRUTH,
                )
                .values_list("id", flat=True)
                .first()
            )
            if not gt_job_id:
                return None

            quality_settings = QualitySettingsManager().get_task_settings(task)
            report_parameters = self.get_report_parameters(task)

            all_job_ids: set[int] = set(
                Job.objects.filter(segment__task=task)
                .exclude(type=JobType.GROUND_TRUTH)
                .values_list("id", flat=True)
            )

            job_filter = JsonLogicFilter()
            if job_filter_rules := job_filter.parse_query(
                quality_settings.job_filter or "[]", raise_on_empty=False
            ):
                job_queryset = job_filter.apply_filter(
                    Job.objects,
                    parsed_rules=job_filter_rules,
                    lookup_fields=self.JOB_FILTER_LOOKUPS,
                )
                filtered_job_ids: set[int] = set(
                    job_id
                    for ids_chunk in take_by(all_job_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE)
                    for job_id in job_queryset.filter(id__in=ids_chunk).values_list("id", flat=True)
                )
            else:
                filtered_job_ids = set(all_job_ids)

            # Try to use a shared queryset to minimize DB requests
            job_queryset = Job.objects.select_related("segment").filter(segment__task=task)

            # Add prefetch data to the shared queryset
            # All the jobs / segments share the same task, so we can load it just once.
            # We reuse the same object for better memory use (OOM is possible otherwise).
            # Perform manual "join", since django can't do this.
            gt_job = JobDataProvider.add_prefetch_info(job_queryset).get(id=gt_job_id)

            jobs: dict[int, Job] = [j for j in job_queryset if j.id in filtered_job_ids]
            for job in job_queryset:
                job.segment.task = gt_job.segment.task  # put the prefetched object

            gt_job_data_provider = JobDataProvider(gt_job.id, queryset=job_queryset)
            active_validation_frames = self.get_active_validation_frames(task, gt_job_data_provider)

            job_data_providers = {
                job.id: JobDataProvider(
                    job.id,
                    queryset=job_queryset,
                    included_frames=active_validation_frames,
                )
                for job in jobs
            }

            quality_requirements = resolve_effective_requirements(
                list(quality_settings.requirements.select_related("parent").all())
            )

            job_comparison_reports: dict[int, ComparisonReport] = {}
            for job in jobs:
                if job.id not in filtered_job_ids:
                    continue

                job_data_provider = job_data_providers[job.id]
                comparator = DatasetQualityEstimator(
                    job_data_provider,
                    gt_job_data_provider,
                    requirements=quality_requirements,
                    report_parameters=report_parameters,
                )
                job_comparison_reports[job.id] = comparator.generate_report()

                # Release resources
                del job_data_provider.dm_dataset

            snapshot = TaskReportSnapshot(
                generation_id=bound_generation.id,
                target_last_updated=task.updated_date,
                gt_last_updated=gt_job.updated_date,
                job_ids=frozenset(j.id for j in jobs),
                job_updated_dates={job.id: job.updated_date for job in jobs},
                assignee_ids={job.id: job.assignee_id for job in jobs},
                assignee_updated_dates={
                    job.id: job.assignee_updated_date for job in jobs
                },
            )

        task_comparison_report = self._compute_task_report(
            job_comparison_reports,
            report_parameters=report_parameters,
            requirements=quality_requirements,
            all_job_ids=all_job_ids,
        )

        return {
            "task": task,
            "bound_generation": bound_generation,
            "snapshot": snapshot,
            "task_comparison_report": task_comparison_report,
            "job_comparison_reports": job_comparison_reports,
        }

    def get_active_validation_frames(self, task: Task, gt_job_data_provider: JobDataProvider):
        active_validation_frames = gt_job_data_provider.job_data.get_included_frames()

        validation_layout = task.data.validation_layout
        if validation_layout.mode == ValidationMode.GT_POOL:
            task_frame_provider = TaskFrameProvider(task)
            active_validation_frames = set(
                task_frame_provider.get_rel_frame_number(abs_frame)
                for abs_frame, abs_real_frame in (
                    Image.objects.filter(data=task.data, is_placeholder=True)
                    .values_list("frame", "real_frame")
                    .iterator(chunk_size=_DEFAULT_FETCH_CHUNK_SIZE)
                )
                if task_frame_provider.get_rel_frame_number(abs_real_frame)
                in active_validation_frames
            )

        return active_validation_frames

    def _compute_task_report(
        self,
        job_reports: dict[int, ComparisonReport],
        report_parameters: ComparisonReportParameters,
        requirements: list[EffectiveQualityRequirement],
        *,
        all_job_ids: set[int],
    ) -> ComparisonReport:
        # Accumulate job stats
        job_stats = ComparisonReportJobStats.create_empty()
        job_stats.all.update(all_job_ids)
        job_stats.excluded.update(all_job_ids - job_reports.keys())
        job_stats.not_checkable.update(
            jid for jid, r in job_reports.items() if not r.comparison_summary.validation_frames
        )
        job_stats.completed.update(
            jid
            for jid, r in job_reports.items()
            if _all_enabled_requirements_completed(r.comparison_summary)
        )

        # The task dataset can be different from any jobs' dataset because of frame overlaps
        # between jobs, from which annotations are merged to get the task annotations.
        # Thus, a separate report could be computed for the task. Instead, here we only
        # compute the combined summary of the job reports.
        # It's possible that overlapped frames checked more than once, ignore extra checks
        # in this statistics and results.
        task_validated_frames = set()
        task_validation_frames_count = 0  # in included and non-checkable jobs
        task_total_frames = 0  # in included and non-checkable jobs
        task_conflicts: list[AnnotationConflict] = []
        task_group_frame_results: dict[str, dict[int, ComparisonReportFrameComparisonSummary]] = {}
        task_group_parameters: dict[str, dict] = {}
        task_group_calculations: dict[str, ComparisonReportRequirementCalculation] = {}
        for r in job_reports.values():
            task_validated_frames.update(r.comparison_summary.frames)
            task_validation_frames_count += r.comparison_summary.validation_frames
            task_total_frames += r.comparison_summary.total_frames
            task_conflicts.extend(r.get_conflicts())

            for group_name, group_report in (r.groups or {}).items():
                task_group_parameters.setdefault(group_name, deepcopy(group_report.parameters))
                task_group_calculations[group_name] = select_requirement_calculation(
                    task_group_calculations.get(group_name),
                    group_report.comparison_summary.calculation,
                )
                group_frame_results = task_group_frame_results.setdefault(group_name, {})

                for frame_id, group_frame_result in (group_report.frame_results or {}).items():
                    merged_group_frame_result = group_frame_results.get(frame_id)

                    if merged_group_frame_result is None:
                        merged_group_frame_result = deepcopy(group_frame_result)
                    else:
                        merge_frame_summaries(merged_group_frame_result, group_frame_result)

                    group_frame_results[frame_id] = merged_group_frame_result

        task_conflicts = deduplicate_annotation_conflicts(task_conflicts)

        requirement_groups = {
            group_name: build_requirement_report(
                requirement=task_group_parameters[group_name],
                frame_results=group_frame_results,
                calculation=task_group_calculations[group_name],
            )
            for group_name, group_frame_results in task_group_frame_results.items()
        }
        for requirement in requirements:
            if not requirement.enabled:
                continue

            requirement_groups.setdefault(
                requirement.name,
                build_requirement_report(
                    requirement=requirement,
                    frame_results={},
                ),
            )

        target_requirements: list = requirements or [
            group_report.parameters for group_report in requirement_groups.values()
        ]
        task_report_data = ComparisonReport(
            parameters=report_parameters,
            comparison_summary=ComparisonReportSummary(
                validation_frames=task_validation_frames_count,
                total_frames=task_total_frames,
                frames=sorted(task_validated_frames),
                conflict_count=len(task_conflicts),
                error_count=len(task_conflicts),
                conflicts_by_type=Counter(c.type for c in task_conflicts),
                tasks=None,
                jobs=job_stats,
                requirements=build_requirements_summary(target_requirements, requirement_groups),
            ),
            groups=requirement_groups,
        )

        return task_report_data

    def get_report_parameters(self, task: Task) -> ComparisonReportParameters:
        quality_settings_manager = QualitySettingsManager()
        task_own_settings = quality_settings_manager.get_task_settings(task, inherit=False)
        task_effective_settings = quality_settings_manager.get_task_settings(task)
        return ComparisonReportParameters.from_settings(
            task_effective_settings, inherited=task_own_settings.id != task_effective_settings.id
        )


class ProjectQualityCalculator:
    def compute_report(
        self,
        project: Project | int,
        *,
        generation_id: int | None = None,
    ) -> models.QualityReport | None:
        if isinstance(project, int):
            project = Project.objects.get(id=project)

        bound_generation_id = generation_id
        for _attempt in range(MAX_STALE_RECOMPUTES + 1):
            snapshot_outputs = self._compute_project_report_snapshot(
                project, generation_id=bound_generation_id
            )
            if snapshot_outputs is None:
                return None

            try:
                return publish_project_report_family(**snapshot_outputs)
            except StaleGenerationError as stale_error:
                ServerLogManager("quality").glob.warning(
                    "Stale quality report snapshot for project id %s, recomputing "
                    "(attempt %s/%s): %s %s",
                    project.id,
                    _attempt + 1,
                    MAX_STALE_RECOMPUTES + 1,
                    stale_error.reason,
                    stale_error.details,
                )
                bound_generation_id = None
                continue

        ServerLogManager("quality").glob.warning(
            "Discarding stale quality report computation for project id %s: "
            "the rules/data generation kept changing; returning the current report",
            project.id,
        )
        return get_current_project_report(project.id)

    def _compute_project_report_snapshot(
        self,
        project: Project,
        *,
        generation_id: int | None,
    ) -> dict | None:
        project = Project.objects.get(id=project.id)
        project_settings = QualitySettingsManager().get_project_settings(project)
        project_report_parameters = self.get_report_parameters(project)
        project_requirements = resolve_effective_requirements(
            list(project_settings.requirements.select_related("parent").all())
        )

        bound_generation = (
            models.QualityRulesGeneration.objects.get(id=generation_id)
            if generation_id is not None
            else None
        )
        if bound_generation is None:
            bound_generation = get_current_rules_generation(project=project)

        # Pin the task set first; tasks added/removed later belong to the next
        # project generation.
        all_task_ids: set[int] = set(
            Task.objects.filter(project=project).values_list("id", flat=True)
        )

        configured_task_ids: set[int] = set(
            task_id
            for ids_chunk in take_by(all_task_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE)
            for task_id in Job.objects.filter(
                type=JobType.GROUND_TRUTH,
                segment__task__in=ids_chunk,
            ).values_list("segment__task__id", flat=True)
        )

        configured_tasks: dict[int, Task] = {}
        for ids_batch in take_by(configured_task_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE):
            tasks_batch = list(
                Task.objects.filter(id__in=ids_batch).select_related("quality_settings")
            )
            configured_tasks.update((t.id, t) for t in tasks_batch)

        task_families = self._get_current_task_families(configured_task_ids)
        gt_updated_dates = self._get_gt_job_updated_dates(configured_task_ids)
        task_jobs = self._get_task_jobs(configured_task_ids)

        selected_families: dict[int, models.QualityReport] = {}
        for task_id, task in configured_tasks.items():
            family = task_families.get(task_id)
            task_settings = self._get_task_own_settings(task)

            if family is not None:
                inherits_project = self._task_inherits_project(task, task_settings)
                fingerprint_matches = (
                    not inherits_project
                    or family.generation.fingerprint == bound_generation.fingerprint
                )
                if fingerprint_matches and self._task_family_is_fresh(
                    family,
                    task=task,
                    gt_updated=gt_updated_dates.get(task_id),
                    jobs=task_jobs.get(task_id, []),
                ):
                    selected_families[task_id] = family
                    continue

            # Deterministic inline recomputation under the task's current
            # generation. For inheriting tasks this is the same fingerprint as
            # the bound project generation; otherwise it is the task's own one.
            with suppress(Task.DoesNotExist):
                task_generation_id = get_current_rules_generation(task=task).id
                new_family = TaskQualityCalculator().compute_report(
                    task,
                    generation_id=task_generation_id,
                )
                if new_family is not None:
                    selected_families[task_id] = new_family

        task_comparison_reports: dict[int, ComparisonReport] = {
            task_id: ComparisonReport.from_json(family.get_report_data())
            for task_id, family in selected_families.items()
        }

        project_comparison_report = self._compute_project_report(
            task_reports=task_comparison_reports,
            report_parameters=project_report_parameters,
            requirements=project_requirements,
            all_task_ids=all_task_ids,
        )

        snapshot = ProjectReportSnapshot(
            generation_id=bound_generation.id,
            project_target_updated=project.updated_date,
            task_family_ids=frozenset(family.id for family in selected_families.values()),
        )

        return {
            "project": project,
            "bound_generation": bound_generation,
            "snapshot": snapshot,
            "project_comparison_report": project_comparison_report,
            "task_families": selected_families,
        }

    @staticmethod
    def _get_task_own_settings(task: Task) -> models.QualitySettings:
        return task.quality_settings

    @staticmethod
    def _task_inherits_project(
        task: Task, own_settings: models.QualitySettings
    ) -> bool:
        return bool(task.project_id and own_settings.inherit)

    @staticmethod
    def _get_current_task_families(
        task_ids: set[int],
    ) -> dict[int, models.QualityReport]:
        families: dict[int, models.QualityReport] = {}
        for ids_batch in take_by(task_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE):
            for family in models.QualityReport.objects.filter(
                task_id__in=ids_batch,
                status=models.QualityReportStatus.CURRENT,
            ).prefetch_related("children"):
                families[family.task_id] = family

        return families

    @staticmethod
    def _get_gt_job_updated_dates(task_ids: set[int]) -> dict[int, datetime]:
        dates: dict[int, datetime] = {}
        for ids_batch in take_by(task_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE):
            rows = (
                Job.objects.filter(type=JobType.GROUND_TRUTH, segment__task__in=ids_batch)
                .values("segment__task_id", "updated_date")
            )
            dates.update({row["segment__task_id"]: row["updated_date"] for row in rows})
        return dates

    @staticmethod
    def _get_task_jobs(task_ids: set[int]) -> dict[int, list[Job]]:
        jobs_by_task: dict[int, list[Job]] = {task_id: [] for task_id in task_ids}
        for ids_batch in take_by(task_ids, chunk_size=_DEFAULT_FETCH_CHUNK_SIZE):
            for job in Job.objects.filter(
                segment__task__in=ids_batch
            ).exclude(type=JobType.GROUND_TRUTH):
                jobs_by_task.setdefault(job.segment.task_id, []).append(job)
        return jobs_by_task

    @staticmethod
    def _task_family_is_fresh(
        family: models.QualityReport,
        *,
        task: Task,
        gt_updated: datetime | None,
        jobs: list[Job],
    ) -> bool:
        if family.status != models.QualityReportStatus.CURRENT:
            return False
        if family.target_last_updated < task.updated_date:
            return False
        if gt_updated is None or (
            family.gt_last_updated is None or family.gt_last_updated < gt_updated
        ):
            return False

        summary = family.summary
        # Sets are serialized as lists in the report JSON
        acceptable_without_report = (
            set(summary.jobs.excluded) | set(summary.jobs.not_checkable)
        )

        child_reports = {
            child.job_id: child
            for child in family.children.all()
            if child.job_id is not None
        }
        for job in jobs:
            child = child_reports.get(job.id)
            if child is None:
                if job.id not in acceptable_without_report:
                    return False
                continue

            if child.status != models.QualityReportStatus.CURRENT:
                return False
            if child.target_last_updated < job.updated_date:
                return False
            if child.assignee_id != job.assignee_id:
                return False
            if child.assignee_last_updated != job.assignee_updated_date:
                return False

        return True

    def _compute_project_report(
        self,
        task_reports: dict[int, ComparisonReport],
        *,
        report_parameters: ComparisonReportParameters,
        requirements: list[EffectiveQualityRequirement],
        all_task_ids: set[int],
    ) -> ComparisonReport:
        # Aggregate nested reports. It's possible that there are no child reports,
        # but we still need to return a meaningful report.

        # Compute task stats
        task_stats = ComparisonReportTaskStats.create_empty()
        task_stats.all.update(all_task_ids)
        task_stats.not_configured.update(all_task_ids - task_reports.keys())
        task_stats.custom.update(
            tid for tid, r in task_reports.items() if not r.parameters.inherited
        )
        task_stats.excluded.update(
            task_stats.all
            - task_stats.not_configured
            - task_stats.custom
            - (
                task_reports.keys()
                - {
                    # Consider tasks excluded if no jobs were included
                    task_id
                    for task_id, r in task_reports.items()
                    if not r.comparison_summary.jobs.included_count
                }
            )
        )

        included_tasks: set[int] = (
            task_reports.keys()
            - task_stats.custom
            - task_stats.not_configured
            - task_stats.excluded
        )
        task_stats.completed.update(
            task_id
            for task_id in included_tasks
            if _all_enabled_requirements_completed(task_reports[task_id].comparison_summary)
        )

        # Accumulate job stats
        job_stats = ComparisonReportJobStats.create_empty()
        for task_id in included_tasks:
            task_report_summary = task_reports[task_id].comparison_summary
            if not task_report_summary.jobs:
                continue

            job_stats.all.update(task_report_summary.jobs.all)
            job_stats.excluded.update(task_report_summary.jobs.excluded)
            job_stats.not_checkable.update(task_report_summary.jobs.not_checkable)
            job_stats.completed.update(task_report_summary.jobs.completed)

        total_frames = 0
        total_validated_frames = 0
        project_conflicts: list[AnnotationConflict] = []
        project_group_parameters: dict[str, dict] = {}
        project_group_annotations: dict[str, ComparisonReportAnnotationsSummary] = {}
        project_group_conflicts: dict[str, list[AnnotationConflict]] = {}
        project_group_calculations: dict[str, ComparisonReportRequirementCalculation] = {}
        for task_id, r in task_reports.items():
            if task_id not in included_tasks:
                continue

            total_frames += r.comparison_summary.total_frames
            total_validated_frames += r.comparison_summary.validation_frames

            project_conflicts.extend(r.get_conflicts())

            for group_name, group_report in (r.groups or {}).items():
                project_group_parameters.setdefault(group_name, deepcopy(group_report.parameters))
                project_group_calculations[group_name] = select_requirement_calculation(
                    project_group_calculations.get(group_name),
                    group_report.comparison_summary.calculation,
                )

                # NOTE @grigorii: Currently, project reports aggregate only actually observed
                # annotations, so every task matrix has weight 1. Keep the extrapolation formula
                # below for a future project estimation mode.
                group_weight = 1
                # group_total_frames = r.comparison_summary.total_frames
                # group_validated_frames = len(group_report.frame_results or {})
                # group_frame_share = group_validated_frames / (group_total_frames or 1)
                # group_weight = 1 / (group_frame_share or 1)
                group_annotations = ComparisonReportAnnotationsSummary.from_confusion_matrix(
                    group_report.comparison_summary.confusion_matrix
                )
                project_group_annotations.setdefault(
                    group_name, ComparisonReportAnnotationsSummary.create_empty()
                ).accumulate(group_annotations, weight=group_weight)
                project_group_conflicts.setdefault(group_name, []).extend(group_report.conflicts)

        requirement_groups = {}
        for group_name, parameters in project_group_parameters.items():
            group_conflicts = deduplicate_annotation_conflicts(
                project_group_conflicts.get(group_name, [])
            )
            requirement_groups[group_name] = ComparisonReportRequirementSummary(
                parameters=parameters,
                comparison_summary=build_requirement_comparison_summary(
                    requirement=parameters,
                    annotations=project_group_annotations[group_name],
                    conflicts=group_conflicts,
                    calculation=project_group_calculations[group_name],
                ),
                frame_results=None,
            )

        for requirement in requirements:
            if not requirement.enabled:
                continue

            requirement_groups.setdefault(
                requirement.name,
                build_requirement_report(
                    requirement=requirement,
                    frame_results={},
                    include_frame_results=False,
                ),
            )

        target_requirements: list = requirements or [
            group_report.parameters for group_report in requirement_groups.values()
        ]
        project_conflicts = deduplicate_annotation_conflicts(project_conflicts)
        project_report_data = ComparisonReport(
            parameters=report_parameters,
            comparison_summary=ComparisonReportSummary(
                total_frames=total_frames,
                validation_frames=total_validated_frames,
                frames=None,  # project reports do not provide this info
                conflict_count=len(project_conflicts),
                error_count=len(project_conflicts),
                conflicts_by_type=Counter(c.type for c in project_conflicts),
                tasks=task_stats,
                jobs=job_stats,
                requirements=build_requirements_summary(target_requirements, requirement_groups),
            ),
            groups=requirement_groups,
        )

        return project_report_data

    def get_report_parameters(self, project: Project) -> ComparisonReportParameters:
        quality_settings = QualitySettingsManager().get_project_settings(project)
        return ComparisonReportParameters.from_settings(quality_settings, inherited=False)
