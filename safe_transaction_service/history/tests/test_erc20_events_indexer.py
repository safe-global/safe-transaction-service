import copy

from django.test import TestCase

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..indexers import Erc20EventsIndexerProvider
from ..models import EthereumEvent, EthereumTx
from .factories import SafeContractFactory


class TestErc20EventsIndexer(EthereumTestCaseMixin, TestCase):
    def test_erc20_events_indexer(self):
        erc20_events_indexer = Erc20EventsIndexerProvider()
        erc20_events_indexer.confirmations = 0
        self.assertEqual(erc20_events_indexer.start(), 0)

        account = self.ethereum_test_account
        amount = 10
        erc20_contract = self.deploy_example_erc20(amount, account.address)

        # PostReceive signal will set the `erc20_block_number` to the `EthereumTx` block number
        safe_contract = SafeContractFactory(ethereum_tx__block__number=0)
        self.assertEqual(safe_contract.erc20_block_number, 0)

        tx_hash = self.ethereum_client.erc20.send_tokens(safe_contract.address, amount, erc20_contract.address,
                                                         account.key)

        self.assertEqual(safe_contract.erc20_block_number, 0)
        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertFalse(EthereumEvent.objects.erc20_tokens_used_by_address(safe_contract.address))

        self.assertEqual(erc20_events_indexer.start(), 1)
        safe_contract.refresh_from_db()

        self.assertEqual(safe_contract.erc20_block_number,
                         self.ethereum_client.current_block_number - erc20_events_indexer.confirmations)
        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertTrue(EthereumEvent.objects.erc20_tokens_used_by_address(safe_contract.address))

        # Test _transform_transfer_event
        block_number = self.ethereum_client.get_transaction(tx_hash)['blockNumber']
        event = self.ethereum_client.erc20.get_total_transfer_history(from_block=block_number, to_block=block_number)[0]
        self.assertIn('value', event['args'])

        original_event = copy.deepcopy(event)
        del event['args']['value']
        event['args']['unknown'] = original_event['args']['value']

        self.assertEqual(erc20_events_indexer._transform_transfer_event(event), original_event)
