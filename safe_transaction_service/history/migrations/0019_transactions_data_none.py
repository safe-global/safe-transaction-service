from django.db import migrations


def set_data_none(apps, schema_editor):
    MultisigTransaction = apps.get_model("history", "MultisigTransaction")
    ModuleTransaction = apps.get_model("history", "ModuleTransaction")
    EthereumTx = apps.get_model("history", "EthereumTx")
    for Model in (MultisigTransaction, ModuleTransaction, EthereumTx):
        Model.objects.filter(data=b"").update(data=None)


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0018_multisigtransaction_trusted"),
    ]

    operations = [
        migrations.RunPython(set_data_none, reverse_code=migrations.RunPython.noop),
    ]
