from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe

from ...models import SafeStatus
from ...services import IndexServiceProvider


class Command(BaseCommand):
    help = 'Check nonce calculated by the indexer is the same that blockchain nonce'

    def add_arguments(self, parser):
        parser.add_argument('--fix', help="Fix nonce problems", action='store_true',
                            default=False)

    def handle(self, *args, **options):
        fix = options['fix']

        queryset = SafeStatus.objects.last_for_every_address()
        count = queryset.count()
        batch = 200
        ethereum_client = EthereumClientProvider()
        index_service = IndexServiceProvider()

        for i in range(0, count, batch):
            self.stdout.write(self.style.SUCCESS(f'Processed {i}/{count}'))
            safe_statuses = queryset[i:i + batch]
            addresses = []
            nonces = []
            for result in safe_statuses.values('address', 'nonce'):
                addresses.append(result['address'])
                nonces.append(result['nonce'])

            blockchain_nonce_fns = [Safe(address, ethereum_client).get_contract().functions.nonce()
                                    for address in addresses]
            blockchain_nonces = ethereum_client.batch_call(blockchain_nonce_fns)

            addresses_to_reindex = []
            for address, nonce, blockchain_nonce in zip(addresses, nonces, blockchain_nonces):
                if nonce != blockchain_nonce:
                    self.stdout.write(self.style.WARNING(f'Safe={address} stored nonce={nonce} is '
                                                         f'different from blockchain-nonce={blockchain_nonce}'))
                    addresses_to_reindex.append(address)

            if fix and addresses_to_reindex:
                self.stdout.write(self.style.SUCCESS(f'Fixing Safes={addresses_to_reindex}'))
                index_service.reindex_addresses(addresses_to_reindex)
