from django.core.management.base import BaseCommand

from ...models import (InternalTxDecoded, MultisigConfirmation,
                       MultisigTransaction, SafeStatus)
from ...tasks import process_decoded_internal_txs_task


class Command(BaseCommand):
    help = 'Delete processed entities and process traces again'

    def add_arguments(self, parser):
        # Positional arguments
        # parser.add_argument('--deployer-key', help='Private key for deployer')
        pass

    def handle(self, *args, **options):
        MultisigConfirmation.objects.filter(signature=None).delete()  # Remove not offchain confirmations
        MultisigTransaction.objects.exclude(ethereum_tx=None).delete()  # Remove not indexed transactions
        SafeStatus.objects.all().delete()
        InternalTxDecoded.objects.update(processed=False)
        process_decoded_internal_txs_task.delay()
        self.stdout.write(self.style.SUCCESS('All prepared to process again'))
