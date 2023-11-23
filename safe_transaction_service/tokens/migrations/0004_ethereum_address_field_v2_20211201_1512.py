# Generated by Django 3.2.9 on 2021-12-01 15:12

from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("tokens", "0003_auto_20201222_1053"),
    ]

    operations = [
        migrations.RunSQL(
            """
            DROP INDEX IF EXISTS tokens_token_address_18ef94ca_like;
            ALTER TABLE "tokens_token" ALTER COLUMN "address" TYPE bytea USING DECODE(SUBSTRING("address", 3), 'hex');
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="token",
            name="address",
            field=gnosis.eth.django.models.EthereumAddressV2Field(
                primary_key=True, serialize=False
            ),
        ),
    ]
