# Generated by Django 2.2.4 on 2019-08-13 09:41

from django.db import migrations
import gnosis.eth.django.models


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0002_auto_20190809_1219'),
    ]

    operations = [
        migrations.AddField(
            model_name='safestatus',
            name='nonce',
            field=gnosis.eth.django.models.Uint256Field(default=0),
        ),
    ]
