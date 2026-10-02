import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conftest  # noqa: F401  # installs the datumaro dummy finder

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_orm")

import django

django.setup()

from django.test.runner import DiscoverRunner

_test_runner = DiscoverRunner(verbosity=0)
_old_db_config = _test_runner.setup_databases()

import hashlib
import json

from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control.generation import compute_rules_fingerprint
from cvat.apps.quality_control.models import QualitySettings

project = Project.objects.create(name="p")
task = Task.objects.create(name="t", project=project)
standalone_task = Task.objects.create(name="t2")
ps = QualitySettings.objects.create(project=project)
ts = QualitySettings.objects.create(task=task)
standalone_ts = QualitySettings.objects.create(task=standalone_task)

# Replicate payload rendering
import cvat.apps.quality_control.generation as g

_orig_compute = g.compute_rules_fingerprint


def _wrapped_compute(*, settings, requirements=None):
    if requirements is None:
        requirements = g.resolve_effective_requirements(
            list(settings.requirements.select_related("parent").all())
        )
    requirements = sorted(
        requirements,
        key=lambda r: (r.sort_order, r.name, r.source_requirement_id or 0),
    )
    payload = {
        "version": g._FINGERPRINT_VERSION,
        "settings": {f: getattr(settings, f) for f in g._SETTINGS_FINGERPRINT_FIELDS},
        "requirements": [g._requirement_to_canonical(r) for r in requirements],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=g._json_default,
    )
    print(">>>", settings.id, canonical)
    return _orig_compute(settings=settings, requirements=requirements)


g.compute_rules_fingerprint = _wrapped_compute

for label, s in (("project", ps), ("task-inherit", ts), ("standalone", standalone_ts)):
    d = g.resolve_rules_generation_descriptor(s)
    print(label, d.fingerprint)

for s in (ps, ts, standalone_ts):
    reqs = g.resolve_effective_requirements(list(s.requirements.select_related("parent").all()))
    payload = {
        "version": g._FINGERPRINT_VERSION,
        "settings": {f: getattr(s, f) for f in g._SETTINGS_FINGERPRINT_FIELDS},
        "requirements": [g._requirement_to_canonical(r) for r in sorted(
            reqs, key=lambda r: (r.sort_order, r.name, r.source_requirement_id or 0)
        )],
    }
    print(s.id, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=g._json_default))
    print(compute_rules_fingerprint(settings=s, requirements=reqs))
