from django.core.management.base import BaseCommand

from ...indexers.tx_decoder import TxDecoder, CannotDecode
from ...models import InternalTxDecoded, InternalTx


class Command(BaseCommand):
    help = 'Decode txs again. Useful when you add a new abi to decode to process old indexed transactions'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Decoding txs again'))
        tx_decoder = TxDecoder()
        found = 0
        for internal_tx in InternalTx.objects.can_be_decoded().iterator():
            try:
                function_name, arguments = tx_decoder.decode_transaction(bytes(internal_tx.data))
                InternalTxDecoded.objects.create(internal_tx=internal_tx,
                                                 function_name=function_name,
                                                 arguments=arguments)
                found += 1
                self.stdout.write(self.style.SUCCESS(f'A new tx with fn-name={function_name} has been decoded'))
            except CannotDecode:
                pass
        self.stdout.write(self.style.SUCCESS(f'End decoding of txs. {found} new txs have been decoded'))
