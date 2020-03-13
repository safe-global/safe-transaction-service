import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import InternalTxDecoded, MultisigTransaction, SafeStatus
from ...tasks import process_decoded_internal_txs_task
from . import decode_txs_again


class Command(BaseCommand):
    help = 'Delete processed entities and process traces again'

    def add_arguments(self, parser):
        parser.add_argument('--sync', help="Don't use an async task", action='store_true',
                            default=False)
        parser.add_argument('--decode', help="Decode txs again", action='store_true',
                            default=False)

    def handle(self, *args, **options):
        sync = options['sync']
        decode = options['decode']

        with transaction.atomic():
            if decode:
                self.stdout.write(self.style.SUCCESS('Deleting InternalTxDecoded'))
                InternalTxDecoded.objects.all().delete()
                self.stdout.write(self.style.SUCCESS('Decoding InternalTxs'))
                call_command(decode_txs_again.Command(), verbosity=0)
                self.stdout.write(self.style.SUCCESS('Decoded InternalTxs'))

            self.stdout.write(self.style.SUCCESS('Removing MultisigTransactions (and confirmations binded)'))
            # Remove mined transactions. This is important, as if `nonce` gets wrong due to a problem of indexing
            # we could be indexing existing txs with wrong SafeTxHash, so they will be duplicated. Deleting this
            # we will retrieve then again from blockchain
            MultisigTransaction.objects.exclude(ethereum_tx=None).delete()
            self.stdout.write(self.style.SUCCESS('Removing SafeStatus objects'))
            SafeStatus.objects.all().delete()

            self.stdout.write(self.style.SUCCESS('Setting all InternalTxDecoded as not Processed'))
            InternalTxDecoded.objects.update(processed=False)

        if not sync:
            process_decoded_internal_txs_task.delay()
        else:
            root_logger = logging.getLogger('')
            root_logger.setLevel(logging.INFO)
            process_decoded_internal_txs_task()
        self.stdout.write(self.style.SUCCESS('All prepared to process again'))
