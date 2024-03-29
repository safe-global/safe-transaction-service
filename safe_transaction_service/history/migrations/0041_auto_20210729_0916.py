# Generated by Django 3.2.5 on 2021-07-29 09:16

from django.db import migrations, models


def migrate_l2_master_copies(apps, schema_editor):
    """
    Migrate SafeL2MasterCopy table elements to SafeMasterCopy table

    :param apps:
    :param schema_editor:
    :return:
    """
    SafeMasterCopy = apps.get_model("history", "SafeMasterCopy")
    SafeL2MasterCopy = apps.get_model("history", "SafeL2MasterCopy")

    for l2_master_copy in SafeL2MasterCopy.custom_manager.all():
        safe_master_copy, _ = SafeMasterCopy.objects.update_or_create(
            address=l2_master_copy.address,
            defaults={
                "initial_block_number": l2_master_copy.initial_block_number,
                "tx_block_number": l2_master_copy.tx_block_number,
                "version": l2_master_copy.version,
                "l2": True,
            },
        )


def migrate_back_l2_master_copies(apps, schema_editor):
    SafeMasterCopy = apps.get_model("history", "SafeMasterCopy")
    SafeL2MasterCopy = apps.get_model("history", "SafeL2MasterCopy")

    for master_copy in SafeMasterCopy.objects.all():
        safe_master_copy, _ = SafeL2MasterCopy.custom_manager.update_or_create(
            address=master_copy.address,
            defaults={
                "initial_block_number": master_copy.initial_block_number,
                "tx_block_number": master_copy.tx_block_number,
                "version": master_copy.version,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0040_auto_20210607_1007"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="safemastercopy",
            managers=[],
        ),
        migrations.AddField(
            model_name="safemastercopy",
            name="l2",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            migrate_l2_master_copies, reverse_code=migrate_back_l2_master_copies
        ),
        migrations.DeleteModel(
            name="SafeL2MasterCopy",
        ),
    ]
