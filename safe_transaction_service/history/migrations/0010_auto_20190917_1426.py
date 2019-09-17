# Generated by Django 2.2.5 on 2019-09-17 14:26

from django.db import migrations
import django.utils.timezone
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0009_ethereumblock_confirmed'),
    ]

    operations = [
        migrations.AddField(
            model_name='multisigconfirmation',
            name='created',
            field=model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created'),
        ),
        migrations.AddField(
            model_name='multisigconfirmation',
            name='modified',
            field=model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified'),
        ),
    ]
