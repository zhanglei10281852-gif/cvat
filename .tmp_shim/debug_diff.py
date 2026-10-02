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

from cvat.apps.engine.models import Project, Task
from cvat.apps.quality_control import generation
from cvat.apps.quality_control.models import QualitySettings

project = Project.objects.create(name="p")
task = Task.objects.create(name="t", project=project)
standalone_task = Task.objects.create(name="t2")
QualitySettings.objects.create(project=project)
QualitySettings.objects.create(task=task)
standalone = QualitySettings.objects.create(task=standalone_task)

pg = generation.get_current_rules_generation(project=project)
sg = generation.get_current_rules_generation(task=standalone_task)

a, b = sg.fingerprint, pg.fingerprint
print(len(a), len(b), a == b)
for i, (ca, cb) in enumerate(zip(a, b)):
    if ca != cb:
        print("first diff at", i, ca, cb, a[max(0, i - 10): i + 10], b[max(0, i - 10): i + 10])
        break
else:
    print("strings equal")
