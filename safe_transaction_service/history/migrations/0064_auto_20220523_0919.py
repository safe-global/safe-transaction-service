# Generated by Django 3.2.13 on 2022-05-23 09:19

import django.contrib.postgres.fields
from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0063_alter_internaltx__from"),
    ]

    operations = [
        migrations.AlterField(
            model_name="safelaststatus",
            name="enabled_modules",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=gnosis.eth.django.models.EthereumAddressV2Field(),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.AlterField(
            model_name="safestatus",
            name="enabled_modules",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=gnosis.eth.django.models.EthereumAddressV2Field(),
                blank=True,
                default=list,
                size=None,
            ),
        ),
    ]
