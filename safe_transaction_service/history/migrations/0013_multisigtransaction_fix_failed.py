from django.db import migrations
from django.db.models import Q

from safe_transaction_service.history.indexers.tx_processor import (
    SafeTxProcessor,
    SafeTxProcessorProvider,
)


def set_failed_for_multisig_txs(apps, schema_editor):
    # We can't import the Person model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    safe_tx_processor: SafeTxProcessor = SafeTxProcessorProvider()
    MultisigTransaction = apps.get_model("history", "MultisigTransaction")
    for multisig_tx in MultisigTransaction.objects.exclude(
        Q(ethereum_tx=None) | Q(failed=True)
    ).select_related("ethereum_tx"):
        current_failed = multisig_tx.failed
        multisig_tx.failed = safe_tx_processor.is_failed(
            multisig_tx.ethereum_tx, multisig_tx.safe_tx_hash
        )
        if multisig_tx.failed != current_failed:
            multisig_tx.save(update_fields=["failed"])


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0012_moduletransaction"),
    ]

    operations = [
        migrations.RunPython(
            set_failed_for_multisig_txs, reverse_code=migrations.RunPython.noop
        ),
    ]
