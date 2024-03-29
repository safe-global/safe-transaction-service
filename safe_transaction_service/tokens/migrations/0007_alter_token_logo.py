# Generated by Django 3.2.12 on 2022-02-16 11:19

from django.db import migrations

import imagekit.models.fields

import safe_transaction_service.tokens.models


class Migration(migrations.Migration):
    dependencies = [
        ("tokens", "0006_auto_20220214_1629"),
    ]

    operations = [
        migrations.AlterField(
            model_name="token",
            name="logo",
            field=imagekit.models.fields.ProcessedImageField(
                blank=True,
                default="",
                upload_to=safe_transaction_service.tokens.models.get_token_logo_path,
            ),
        ),
    ]
