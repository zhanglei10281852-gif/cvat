import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conftest  # noqa: F401

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_orm")

import django

django.setup()

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=0)
old = runner.setup_databases()

import cvat.apps.quality_control.signals  # noqa
from cvat.apps.engine.models import Task
from cvat.apps.quality_control.models import QualitySettings

t = Task.objects.create(name="t")
s = QualitySettings.objects.get(task=t)
print("standalone created version:", s.rules_version, "reqs:", s.requirements.count())

p = __import__(
    "cvat.apps.engine.models", fromlist=["Project"]
).Project.objects.create(name="p")
t2 = Task.objects.create(name="t2", project=p)
s2 = QualitySettings.objects.get(task=t2)
print("project task version:", s2.rules_version, "reqs:", s2.requirements.count())
