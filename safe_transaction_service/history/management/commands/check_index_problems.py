from typing import Any, Dict, Iterable

from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import Safe

from ...models import MultisigTransaction, SafeStatus
from ...services import IndexServiceProvider


class Command(BaseCommand):
    help = 'Check nonce calculated by the indexer is the same that blockchain nonce'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nonce_fn = Safe(NULL_ADDRESS, EthereumClientProvider()).get_contract().functions.nonce()

    def add_arguments(self, parser):
        parser.add_argument('--fix', help="Fix nonce problems", action='store_true',
                            default=False)

    def build_nonce_payload(self, addresses: Iterable[str]) -> Iterable[Dict[str, Any]]:
        """
        It looks like web3 takes time generating contract functions, so I do it this way
        :param addresses:
        :return:
        """
        contract_function = self.nonce_fn

        payloads = []
        data = contract_function.buildTransaction({'gas': 0, 'gasPrice': 0})['data']
        output_type = [output['type'] for output in contract_function.abi['outputs']]
        fn_name = contract_function.fn_name,  # For debugging purposes
        for address in addresses:
            payload = {'to': address,
                       'data': data,
                       'output_type': output_type,
                       'fn_name': fn_name,
                       }
            payloads.append(payload)
        return payloads

    def handle(self, *args, **options):
        fix = options['fix']

        queryset = SafeStatus.objects.last_for_every_address()
        count = queryset.count()
        batch = 100
        ethereum_client = EthereumClientProvider()
        index_service = IndexServiceProvider()

        for i in range(0, count, batch):
            self.stdout.write(self.style.SUCCESS(f'Processed {i}/{count}'))
            safe_statuses = queryset[i:i + batch]
            safe_statuses_list = list(safe_statuses)  # Force retrieve queryset from DB
            blockchain_nonce_payloads = self.build_nonce_payload([safe_status.address
                                                                  for safe_status in safe_statuses_list])
            blockchain_nonces = ethereum_client.batch_call_custom(blockchain_nonce_payloads, raise_exception=False)

            addresses_to_reindex = set()
            for safe_status, blockchain_nonce in zip(safe_statuses_list, blockchain_nonces):
                address = safe_status.address
                nonce = safe_status.nonce
                if safe_status.is_corrupted():
                    self.stdout.write(self.style.WARNING(f'Safe={address} is corrupted, has some old '
                                                         f'transactions missing'))
                    addresses_to_reindex.add(address)

                if blockchain_nonce is None:
                    self.stdout.write(self.style.WARNING(f'Safe={address} looks problematic, '
                                                         f'cannot retrieve blockchain-nonce'))
                if nonce != blockchain_nonce:
                    self.stdout.write(self.style.WARNING(f'Safe={address} stored nonce={nonce} is '
                                                         f'different from blockchain-nonce={blockchain_nonce}'))
                    if last_valid_transaction := MultisigTransaction.objects.last_valid_transaction(address):
                        self.stdout.write(self.style.WARNING(
                            f'Last valid transaction for Safe={address} has safe-nonce={last_valid_transaction.nonce} '
                            f'safe-transaction-hash={last_valid_transaction.safe_tx_hash} and '
                            f'ethereum-tx-hash={last_valid_transaction.ethereum_tx_id}'))
                    addresses_to_reindex.add(address)

            if fix and addresses_to_reindex:
                self.stdout.write(self.style.SUCCESS(f'Fixing Safes={addresses_to_reindex}'))
                index_service.reindex_addresses(addresses_to_reindex)
