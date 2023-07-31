# Generated by Django 4.2.3 on 2023-07-31 15:13

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0073_safe_apps_links"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="internaltx",
            index=models.Index(
                condition=models.Q(("call_type", 0), ("value__gt", 0)),
                fields=["to", "call_type", "value"],
                name="internaltx_ether_transfer_idx",
            ),
        ),
    ]
