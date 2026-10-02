# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0107_remove_annotationguide_is_public"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackingCSMigration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("to_backing_cs", "to the backing cloud storage"),
                            ("from_backing_cs", "from the backing cloud storage"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[("copy", "Copying"), ("clean", "Cleaning up the source")],
                        default="copy",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "data",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="backing_cs_migration",
                        to="engine.data",
                    ),
                ),
                (
                    "target_cs",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="engine.cloudstorage",
                    ),
                ),
            ],
            options={
                "default_permissions": (),
            },
        ),
    ]
