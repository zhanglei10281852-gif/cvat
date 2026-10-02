# Render the SQL of quality_control migrations without the full migration graph.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_mig")

import django

django.setup()

from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState

real_apps = {
    config.label for config in apps.get_app_configs() if config.label != "quality_control"
}

loader = MigrationLoader(connection, ignore_no_migrations=True)
nodes = [
    node
    for node in loader.graph.nodes
    if node[0] == "quality_control"
]
target = max(nodes, key=lambda node: node[1])
nodes = loader.graph.forwards_plan(target)
migrations = [loader.graph.nodes[n] for n in nodes if n[0] == "quality_control"]
migrations.sort(key=lambda m: m.name)

state = ProjectState(real_apps=real_apps)
with connection.schema_editor(collect_sql=True) as schema_editor:
    for migration in migrations:
        state = migration.apply(state, schema_editor, collect_sql=True)

for line in schema_editor.collected_sql:
    print(line)
