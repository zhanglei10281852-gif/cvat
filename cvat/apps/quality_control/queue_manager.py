# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from typing import ClassVar

import attrs
from django.conf import settings
from rest_framework import serializers
from rq.job import Job as RQJob

from cvat.apps.engine.models import DimensionType, RequestTarget
from cvat.apps.engine.rq import BaseRQMeta
from cvat.apps.profiler import silk_profile
from cvat.apps.redis_handler.background import AbstractRequestManager
from cvat.apps.redis_handler.rq import RequestIdWithSubresource
from cvat.apps.quality_control.quality_calculators import (
    ProjectQualityCalculator,
    TaskQualityCalculator,
)


QualityRequestId = str


@attrs.frozen(kw_only=True)
class QualityRequestId(RequestIdWithSubresource):
    # will be deleted after several releases in the quality reports.
    LEGACY_FORMAT_PATTERNS: ClassVar[tuple[str]] = (
        r"quality-check-(?P<target>task|project)-(?P<target_id>\d+)-user-(\d+)",
    )
    ACTION_DEFAULT_VALUE: ClassVar[str] = "calculate"
    ACTION_ALLOWED_VALUES: ClassVar[tuple[str]] = (ACTION_DEFAULT_VALUE,)
    SUBRESOURCE_DEFAULT_VALUE: ClassVar[str] = "quality"
    SUBRESOURCE_ALLOWED_VALUES: ClassVar[tuple[str]] = (SUBRESOURCE_DEFAULT_VALUE,)

    # Parsed quality rules generation bound to the request; populated by the
    # queue manager when the request is enqueued. It is not part of the request
    # id string, but it is passed as a job callback keyword argument.
    generation_id: int | None = None


class QualityReportQueueManager(AbstractRequestManager):
    QUEUE_NAME = settings.CVAT_QUEUES.QUALITY_REPORTS.value
    SUPPORTED_TARGETS: ClassVar[set[RequestTarget]] = {RequestTarget.TASK, RequestTarget.PROJECT}

    @property
    def job_result_ttl(self):
        return 120

    def get_job_by_id(self, id_: str, /) -> RQJob:
        try:
            id_ = QualityRequestId.parse_and_validate_queue(
                id_,
                expected_queue=self.QUEUE_NAME,
                try_legacy_format=True,
            ).rq_id
        except ValueError:
            raise serializers.ValidationError("Provided request id is invalid")
        return super().get_job_by_id(id_)

    def validate_request(self):
        super().validate_request()

        if self.target == DimensionType.TASK:
            if self.db_instance.dimension != DimensionType.DIM_2D:
                raise serializers.ValidationError("Quality reports are only supported in 2d tasks")
            if self.db_instance.gt_job is None:
                raise serializers.ValidationError(
                    "Quality reports require a Ground Truth job in the task"
                )
        elif isinstance(self.db_instance, Project):  # nothing prevents project reports
            # nothing prevents quality reports
            pass
        else:
            assert False

    def _bind_rules_generation(self) -> int:
        from cvat.apps.quality_control.generation import get_current_rules_generation

        generation = get_current_rules_generation(
            task=self.db_instance if self.target == RequestTarget.TASK else None,
            project=(
                self.db_instance if self.target == RequestTarget.PROJECT else None
            ),
        )
        return generation.id

    def init_request_args(self):
        """Hook to initialize args based on request

        Method should initialize callback args based on request

        """
        self.callback_args = {}
        self.callback_kwargs = {}

    def setup_new_job(self, queue, request_id: str, **kwargs):
        # Bind the complete effective rules generation at enqueue time
        self.callback_kwargs["generation_id"] = self._bind_rules_generation()
        return super().setup_new_job(queue, request_id, **kwargs)


class QualityReportManager:
    @classmethod
    @silk_profile()
    def check_task_quality(*, task_id: int, generation_id: int | None = None) -> int | None:
        report = TaskQualityCalculator().compute_report(task_id, generation_id=generation_id)

        if not report:
            return None

        return report.id

    @classmethod
    @silk_profile()
    def check_project_quality(
        *, project_id: int, generation_id: int | None = None
    ) -> int | None:
        report = ProjectQualityCalculator().compute_report(
            project_id, generation_id=generation_id
        )
        if not report:
            return None
        return report.id
