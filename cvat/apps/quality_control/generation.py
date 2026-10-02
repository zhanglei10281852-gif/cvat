# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from cvat.apps.quality_control import models
from cvat.apps.quality_control.quality_handlers import (
    EffectiveQualityRequirement,
    resolve_effective_requirements,
)

if TYPE_CHECKING:
    from cvat.apps.engine.models import Project, Task

# Bump when the fingerprint payload format changes
_FINGERPRINT_VERSION = 1

# EffectiveQualityRequirement fields identifying the complete effective rule content
_REQUIREMENT_FINGERPRINT_FIELDS = (
    "name",
    "enabled",
    "filter",
    "annotation_type",
    "target_metric",
    "target_metric_threshold",
    "source_requirement_id",
    "parent_requirement",
    "sort_order",
    "iou_threshold",
    "oks_sigma",
    "line_thickness",
    "point_size_base",
    "compare_line_orientation",
    "line_orientation_threshold",
    "compare_groups",
    "group_match_threshold",
    "check_covered_annotations",
    "object_visibility_threshold",
    "panoptic_comparison",
    "compare_attributes",
    "attribute_comparison",
)

_SETTINGS_FINGERPRINT_FIELDS = (
    "job_filter",
    "max_validations_per_job",
)


@dataclass(frozen=True)
class RulesGenerationDescriptor:
    scope_settings_id: int
    own_rules_version: int
    inherit: bool
    source_settings_id: int
    source_rules_version: int
    fingerprint: str


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value

    raise TypeError(f"Unsupported fingerprint value type: {type(value)!r}")


def _requirement_to_canonical(requirement: EffectiveQualityRequirement) -> dict[str, Any]:
    canonical = {}
    for field_name in _REQUIREMENT_FINGERPRINT_FIELDS:
        value = getattr(requirement, field_name)
        if field_name == "target_metric" and value is not None:
            value = str(value)

        canonical[field_name] = value

    return canonical


def compute_rules_fingerprint(
    *,
    settings: models.QualitySettings,
    requirements: list[EffectiveQualityRequirement] | None = None,
) -> str:
    """
    Produce a stable identity of the complete effective rule set for the given settings.
    Equal effective rule content (including a project settings and its inheriting tasks)
    produces an equal fingerprint.
    """
    if requirements is None:
        requirements = resolve_effective_requirements(
            list(settings.requirements.select_related("parent").all())
        )

    requirements = sorted(
        requirements,
        key=lambda r: (r.sort_order, r.name, r.source_requirement_id or 0),
    )

    payload = {
        "version": _FINGERPRINT_VERSION,
        "settings": {
            field_name: getattr(settings, field_name)
            for field_name in _SETTINGS_FINGERPRINT_FIELDS
        },
        "requirements": [_requirement_to_canonical(r) for r in requirements],
    }
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _get_scope_settings(
    *,
    task: Task | None = None,
    project: Project | None = None,
    settings: models.QualitySettings | None = None,
) -> models.QualitySettings:
    if settings is not None:
        return settings

    if project is not None:
        quality_settings, _ = models.QualitySettings.objects.get_or_create(project=project)
        return quality_settings

    if task is not None:
        try:
            return task.quality_settings
        except models.QualitySettings.DoesNotExist:
            return models.QualitySettings.objects.create(task=task)

    raise ValueError("Either task, project or settings must be specified")


def _resolve_source_settings(
    scope_settings: models.QualitySettings,
) -> tuple[models.QualitySettings, bool]:
    """Resolve the settings providing the effective rules, and whether they are inherited."""
    if scope_settings.project_id is not None or not scope_settings.inherit:
        return scope_settings, False

    task = scope_settings.task
    if task is None or task.project_id is None:
        return scope_settings, False

    source_settings, _ = models.QualitySettings.objects.get_or_create(
        project_id=task.project_id
    )
    return source_settings, True


def resolve_rules_generation_descriptor(
    scope_settings: models.QualitySettings,
) -> RulesGenerationDescriptor:
    source_settings, inherit = _resolve_source_settings(scope_settings)
    return RulesGenerationDescriptor(
        scope_settings_id=scope_settings.id,
        own_rules_version=scope_settings.rules_version,
        inherit=inherit,
        source_settings_id=source_settings.id,
        source_rules_version=source_settings.rules_version,
        fingerprint=compute_rules_fingerprint(settings=source_settings),
    )


def get_or_create_rules_generation(
    scope_settings: models.QualitySettings,
) -> models.QualityRulesGeneration:
    """
    Return the immutable rules generation matching the current effective rules of the scope
    settings. The same descriptor always resolves to the same generation row.
    """
    descriptor = resolve_rules_generation_descriptor(scope_settings)

    def _fetch() -> models.QualityRulesGeneration:
        return models.QualityRulesGeneration.objects.get(
            scope_settings_id=descriptor.scope_settings_id,
            own_rules_version=descriptor.own_rules_version,
            inherit=descriptor.inherit,
            source_settings_id=descriptor.source_settings_id,
            source_rules_version=descriptor.source_rules_version,
        )

    try:
        return _fetch()
    except models.QualityRulesGeneration.DoesNotExist:
        generation = models.QualityRulesGeneration(
            scope_settings_id=descriptor.scope_settings_id,
            own_rules_version=descriptor.own_rules_version,
            inherit=descriptor.inherit,
            source_settings_id=descriptor.source_settings_id,
            source_rules_version=descriptor.source_rules_version,
            fingerprint=descriptor.fingerprint,
        )
        # The insert runs in its own savepoint so a concurrent creator winning
        # the unique-descriptor race does not poison an enclosing transaction
        # (publication publishes inside transaction.atomic()). The winning row
        # may still be uncommitted, hence the bounded retry.
        for _attempt in range(3):
            try:
                with transaction.atomic():
                    generation.save()
                return generation
            except IntegrityError:
                try:
                    return _fetch()
                except models.QualityRulesGeneration.DoesNotExist:
                    continue

        return _fetch()


def get_current_rules_generation(
    *,
    task: Task | None = None,
    project: Project | None = None,
    settings: models.QualitySettings | None = None,
) -> models.QualityRulesGeneration:
    scope_settings = _get_scope_settings(task=task, project=project, settings=settings)
    return get_or_create_rules_generation(scope_settings)


def is_rules_generation_current(
    generation: models.QualityRulesGeneration,
    *,
    task: Task | None = None,
    project: Project | None = None,
    settings: models.QualitySettings | None = None,
) -> bool:
    scope_settings = _get_scope_settings(task=task, project=project, settings=settings)
    current = get_or_create_rules_generation(scope_settings)
    return current.id == generation.id


def bump_rules_version(quality_settings: models.QualitySettings) -> int:
    """
    Atomically advance the settings rules version and refresh updated_date.
    Multiple statement calls in a single transaction each advance the version;
    callers performing composite writes must invoke this exactly once per operation.
    """
    updated_count = (
        models.QualitySettings.objects.filter(pk=quality_settings.pk)
        .update(
            rules_version=F("rules_version") + 1,
            updated_date=timezone.now(),
        )
    )
    if updated_count:
        quality_settings.refresh_from_db(fields=("rules_version", "updated_date"))

    return updated_count
