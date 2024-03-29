# Generated by Django 3.2.7 on 2021-09-27 15:15

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0042_safestatus_history_saf_address_1c362b_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="safecontractdelegate",
            name="safe_contract",
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="safe_contract_delegates",
                to="history.safecontract",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="safecontractdelegate",
            unique_together={("safe_contract", "delegate", "delegator")},
        ),
    ]
