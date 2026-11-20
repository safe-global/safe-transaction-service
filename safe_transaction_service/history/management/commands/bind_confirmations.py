from django.core.management.base import BaseCommand

from ...models import MultisigConfirmation, MultisigTransaction


class Command(BaseCommand):
    help = "Binds confirmations with multisig txs"

    def handle(self, *args, **options):
        for multisig_confirmation in (
            MultisigConfirmation.objects.without_transaction()
            .exclude(safe_address=None)
            .iterator()
        ):
            tx = MultisigTransaction.objects.filter(
                safe_tx_hash=multisig_confirmation.multisig_transaction_hash,
                safe=multisig_confirmation.safe_address,
            ).first()
            if tx:
                multisig_confirmation.multisig_transaction = tx
                multisig_confirmation.save(update_fields=["multisig_transaction"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Bind confirmation with multisig tx={tx.safe_tx_hash}"
                    )
                )
