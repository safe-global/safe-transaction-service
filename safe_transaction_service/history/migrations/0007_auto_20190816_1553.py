# Generated by Django 2.2.4 on 2019-08-16 15:53

from django.db import migrations
import gnosis.eth.django.models


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0006_auto_20190816_1128'),
    ]

    operations = [
        migrations.AlterField(
            model_name='multisigconfirmation',
            name='multisig_transaction_hash',
            field=gnosis.eth.django.models.Sha3HashField(db_index=True, null=True),
        ),
    ]
