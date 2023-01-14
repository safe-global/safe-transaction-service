import copy
from unittest import mock

from django.test import TestCase

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..indexers import Erc20EventsIndexer, Erc20EventsIndexerProvider
from ..models import ERC20Transfer, EthereumTx, IndexingStatus
from .factories import SafeContractFactory


class TestErc20EventsIndexer(EthereumTestCaseMixin, TestCase):
    def test_erc20_events_indexer(self):
        erc20_events_indexer = Erc20EventsIndexerProvider()
        erc20_events_indexer.confirmations = 0
        self.assertEqual(erc20_events_indexer.start(), 0)

        account = self.ethereum_test_account
        amount = 10
        erc20_contract = self.deploy_example_erc20(amount, account.address)

        safe_contract = SafeContractFactory()
        IndexingStatus.objects.set_erc20_721_indexing_status(0)
        tx_hash = self.ethereum_client.erc20.send_tokens(
            safe_contract.address, amount, erc20_contract.address, account.key
        )

        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertFalse(
            ERC20Transfer.objects.tokens_used_by_address(safe_contract.address)
        )

        self.assertEqual(erc20_events_indexer.start(), 1)

        # Erc20/721 last indexed block number is stored on IndexingStatus
        self.assertGreater(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )

        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            self.ethereum_client.current_block_number
            - erc20_events_indexer.confirmations,
        )
        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertTrue(
            ERC20Transfer.objects.tokens_used_by_address(safe_contract.address)
        )

        self.assertEqual(
            ERC20Transfer.objects.to_or_from(safe_contract.address).count(), 1
        )

        # Test _process_decoded_element
        block_number = self.ethereum_client.get_transaction(tx_hash)["blockNumber"]
        event = self.ethereum_client.erc20.get_total_transfer_history(
            from_block=block_number, to_block=block_number
        )[0]
        self.assertIn("value", event["args"])

        original_event = copy.deepcopy(event)
        event["args"]["unknown"] = event["args"].pop("value")

        self.assertEqual(
            erc20_events_indexer._process_decoded_element(event), original_event
        )

        # Test ERC721
        event = self.ethereum_client.erc20.get_total_transfer_history(
            from_block=block_number, to_block=block_number
        )[0]
        with mock.patch.object(
            Erc20EventsIndexer, "_is_erc20", autospec=True, return_value=False
        ):
            # Convert event to erc721
            event["args"]["tokenId"] = event["args"].pop("value")
            original_event = copy.deepcopy(event)
            event["args"]["unknown"] = event["args"].pop("tokenId")

            self.assertEqual(
                erc20_events_indexer._process_decoded_element(event), original_event
            )

        event = self.ethereum_client.erc20.get_total_transfer_history(
            from_block=block_number, to_block=block_number
        )[0]
        with mock.patch.object(
            Erc20EventsIndexer, "_is_erc20", autospec=True, return_value=True
        ):
            # Convert event to erc721
            original_event = copy.deepcopy(event)
            event["args"]["tokenId"] = event["args"].pop("value")

            # ERC721 event will be converted to ERC20
            self.assertEqual(
                erc20_events_indexer._process_decoded_element(event), original_event
            )
