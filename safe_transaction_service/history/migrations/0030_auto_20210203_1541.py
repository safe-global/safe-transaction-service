# Generated by Django 3.1.5 on 2021-02-03 15:41

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0029_auto_20201118_1015"),
    ]

    operations = [
        migrations.AlterField(
            model_name="multisigtransaction",
            name="origin",
            field=models.CharField(default=None, max_length=200, null=True),
        ),
    ]
