# Generated by Django 5.0.7 on 2024-07-19 12:53

from django.db import migrations

import safe_eth.eth.django.models


class Migration(migrations.Migration):

    dependencies = [
        (
            "account_abstraction",
            "0004_rename_call_data_gas_limit_useroperation_call_gas_limit",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="safeoperation",
            name="module_address",
            field=safe_eth.eth.django.models.EthereumAddressBinaryField(db_index=True),
        ),
        migrations.AlterField(
            model_name="safeoperationconfirmation",
            name="owner",
            field=safe_eth.eth.django.models.EthereumAddressBinaryField(),
        ),
        migrations.AlterField(
            model_name="useroperation",
            name="entry_point",
            field=safe_eth.eth.django.models.EthereumAddressBinaryField(db_index=True),
        ),
        migrations.AlterField(
            model_name="useroperation",
            name="paymaster",
            field=safe_eth.eth.django.models.EthereumAddressBinaryField(
                blank=True, db_index=True, null=True
            ),
        ),
        migrations.AlterField(
            model_name="useroperation",
            name="sender",
            field=safe_eth.eth.django.models.EthereumAddressBinaryField(db_index=True),
        ),
    ]
