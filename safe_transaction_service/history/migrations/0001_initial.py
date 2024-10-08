# Generated by Django 2.2.2 on 2019-06-18 16:13

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import model_utils.fields
import safe_eth.eth.django.models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MultisigTransaction",
            fields=[
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "safe_tx_hash",
                    safe_eth.eth.django.models.Sha3HashField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("safe", safe_eth.eth.django.models.EthereumAddressField()),
                ("to", safe_eth.eth.django.models.EthereumAddressField()),
                ("value", safe_eth.eth.django.models.Uint256Field()),
                ("data", models.BinaryField(null=True)),
                (
                    "operation",
                    models.PositiveSmallIntegerField(
                        choices=[(0, "CALL"), (1, "DELEGATE_CALL"), (2, "CREATE")]
                    ),
                ),
                ("safe_tx_gas", safe_eth.eth.django.models.Uint256Field()),
                ("base_gas", safe_eth.eth.django.models.Uint256Field()),
                ("gas_price", safe_eth.eth.django.models.Uint256Field()),
                (
                    "gas_token",
                    safe_eth.eth.django.models.EthereumAddressField(null=True),
                ),
                (
                    "refund_receiver",
                    safe_eth.eth.django.models.EthereumAddressField(null=True),
                ),
                ("nonce", safe_eth.eth.django.models.Uint256Field()),
                ("mined", models.BooleanField(default=False)),
                ("execution_date", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="MultisigConfirmation",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("owner", safe_eth.eth.django.models.EthereumAddressField()),
                ("transaction_hash", safe_eth.eth.django.models.Sha3HashField()),
                (
                    "confirmation_type",
                    models.PositiveSmallIntegerField(
                        choices=[(0, "CONFIRMATION"), (1, "EXECUTION")]
                    ),
                ),
                ("block_number", safe_eth.eth.django.models.Uint256Field()),
                ("block_date_time", models.DateTimeField()),
                ("mined", models.BooleanField(default=False)),
                (
                    "multisig_transaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="confirmations",
                        to="history.MultisigTransaction",
                    ),
                ),
            ],
            options={
                "unique_together": {
                    ("multisig_transaction", "owner", "confirmation_type")
                },
            },
        ),
    ]
