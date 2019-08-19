from django.core.management.base import BaseCommand

from ...models import MultisigConfirmation, MultisigTransaction


class Command(BaseCommand):
    help = 'Binds confirmations with multisig txs'

    def add_arguments(self, parser):
        # Positional arguments
        # parser.add_argument('--deployer-key', help='Private key for deployer')
        pass

    def handle(self, *args, **options):
        for multisig_confirmation in MultisigConfirmation.objects.without_transaction():
            try:
                tx = MultisigTransaction.objects.get(safe_tx_hash=multisig_confirmation.multisig_transaction_hash)
                multisig_confirmation.multisig_transaction = tx
                multisig_confirmation.save(update_fields=['multisig_transaction'])
                self.stdout.write(self.style.SUCCESS(f'Bind confirmation with multisig tx={tx.safe_tx_hash}'))
            except MultisigTransaction.DoesNotExist:
                pass
