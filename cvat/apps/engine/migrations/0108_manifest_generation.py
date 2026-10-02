# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0107_remove_annotationguide_is_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="manifest",
            name="generation",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="manifest",
            name="remote_last_modified",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="manifest",
            name="local_snapshot",
            field=models.CharField(blank=True, max_length=1024, null=True),
        ),
    ]
