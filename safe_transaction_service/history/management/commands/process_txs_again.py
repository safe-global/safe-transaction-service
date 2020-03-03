import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import InternalTxDecoded, MultisigTransaction, SafeStatus
from ...tasks import process_decoded_internal_txs_task


class Command(BaseCommand):
    help = 'Delete processed entities and process traces again'

    def add_arguments(self, parser):
        parser.add_argument('--sync', help="Don't use an async task", action='store_true',
                            default=False)

    def handle(self, *args, **options):
        sync = options['sync']

        with transaction.atomic():
            self.stdout.write(self.style.SUCCESS('Removing models'))

            # Remove mined transactions. This is important, as if `nonce` gets wrong due to a problem of indexing
            # we could be indexing existing txs with wrong SafeTxHash, so they will be duplicated. Deleting this
            # we will retrieve then again from blockchain
            MultisigTransaction.objects.exclude(ethereum_tx=None).delete()
            SafeStatus.objects.all().delete()

            self.stdout.write(self.style.SUCCESS('Set all InternalTxDecoded as not Processed'))
            InternalTxDecoded.objects.update(processed=False)

        if not sync:
            process_decoded_internal_txs_task.delay()
        else:
            root_logger = logging.getLogger('')
            root_logger.setLevel(logging.INFO)
            process_decoded_internal_txs_task()
        self.stdout.write(self.style.SUCCESS('All prepared to process again'))
