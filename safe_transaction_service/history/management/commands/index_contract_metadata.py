from itertools import islice

from django.core.management.base import BaseCommand

from safe_transaction_service.contracts.tasks import \
    index_contracts_metadata_task

from ...models import MultisigTransaction


class Command(BaseCommand):
    help = 'Index metadata for contracts used by Multisig txs'

    def add_arguments(self, parser):
        parser.add_argument('--addresses', nargs='+',
                            help='Index provided contract addresses instead of the ones from multisig txs on database')
        parser.add_argument('--sync', help="Don't use an async task", action='store_true', default=False)
        parser.add_argument('--batch', help='Number of contracts to index together', type=int, default=100)

    def handle(self, *args, **options):
        addresses = options['addresses']
        sync = options['sync']
        batch = options['batch']

        addresses = addresses or list(MultisigTransaction.objects.not_indexed_metadata_contract_addresses())
        addresses_iter = iter(addresses)
        fn = index_contracts_metadata_task if sync else index_contracts_metadata_task.delay

        while addresses_batch := list(islice(addresses_iter, batch)):
            fn(addresses_batch)
