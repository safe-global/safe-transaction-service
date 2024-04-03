from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from gnosis.eth import EthereumClient
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..indexers import Erc20EventsIndexerProvider
from ..models import (
    ERC20Transfer,
    EthereumBlock,
    EthereumTx,
    IndexingStatus,
    ProxyFactory,
    SafeMasterCopy,
)
from ..services import ReorgServiceProvider
from .factories import (
    EthereumBlockFactory,
    EthereumTxFactory,
    ProxyFactoryFactory,
    SafeContractFactory,
    SafeMasterCopyFactory,
)
from .mocks.mocks_internal_tx_indexer import block_child, block_parent


class TestReorgService(EthereumTestCaseMixin, TestCase):
    @mock.patch.object(EthereumClient, "get_blocks")
    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_check_reorgs(
        self, current_block_number_mock: PropertyMock, get_blocks_mock: MagicMock
    ):
        reorg_service = ReorgServiceProvider()

        block = block_child
        block_number = block["number"]

        get_blocks_mock.return_value = [block_child, block_parent]
        current_block_number = block_number + 100
        current_block_number_mock.return_value = current_block_number

        ethereum_block: EthereumBlock = EthereumBlockFactory(
            number=block_number, confirmed=False
        )
        self.assertEqual(reorg_service.check_reorgs(), block_number)

        ethereum_block.block_hash = block["hash"]
        ethereum_block.save(update_fields=["block_hash"])
        self.assertIsNone(reorg_service.check_reorgs())
        ethereum_block.refresh_from_db()
        self.assertTrue(ethereum_block.confirmed)

    def test_reset_all_to_block(self):
        reorg_service = ReorgServiceProvider()

        elements = 3
        for i in range(elements):
            ProxyFactoryFactory(tx_block_number=100 * i)
            SafeMasterCopyFactory(tx_block_number=300 * i)

        block_number = 5
        reorg_service.reset_all_to_block(block_number)

        # All elements but 1 will be reset (with `tx_block_number=0` and `erc20_block_number=0`)
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            block_number,
        )
        self.assertEqual(
            ProxyFactory.objects.filter(tx_block_number=block_number).count(),
            elements - 1,
        )
        self.assertEqual(
            SafeMasterCopy.objects.filter(tx_block_number=block_number).count(),
            elements - 1,
        )

    def test_recover_from_reorg(self):
        reorg_service = ReorgServiceProvider()

        reorg_block = 2000  # Test a reorg in block 2000
        ethereum_blocks = [
            EthereumBlockFactory(number=reorg_block + i)
            for i in range(-1000, 1001, 500)
        ]
        ethereum_txs = [
            EthereumTxFactory(block=ethereum_block)
            for ethereum_block in ethereum_blocks
        ]
        safe_ethereum_tx = ethereum_txs[0]  # This tx will not be touched by the reorg

        self.assertEqual(EthereumTx.objects.count(), len(ethereum_blocks))

        proxy_factory = ProxyFactoryFactory(tx_block_number=reorg_block)
        indexing_status = IndexingStatus.objects.get_erc20_721_indexing_status()
        indexing_status.block_number = reorg_block - 500
        indexing_status.save(update_fields=["block_number"])
        safe_master_copy = SafeMasterCopyFactory(tx_block_number=reorg_block + 500)

        reorg_service.recover_from_reorg(reorg_block)

        # Check that blocks and ethereum txs were deleted
        self.assertEqual(EthereumBlock.objects.count(), 2)
        self.assertEqual(
            EthereumBlock.objects.filter(number__gte=reorg_block).count(), 0
        )
        self.assertEqual(EthereumTx.objects.count(), 2)

        # Check that indexer rewound needed blocks
        expected_rewind_block = reorg_block - reorg_service.eth_reorg_rewind_blocks
        proxy_factory.refresh_from_db()
        indexing_status.refresh_from_db()
        safe_master_copy.refresh_from_db()
        self.assertEqual(proxy_factory.tx_block_number, expected_rewind_block)
        self.assertEqual(indexing_status.block_number, expected_rewind_block)
        self.assertEqual(safe_master_copy.tx_block_number, expected_rewind_block)

    def test_reorg_with_indexer(self):
        reorg_service = ReorgServiceProvider()
        erc20_events_indexer = Erc20EventsIndexerProvider()
        erc20_events_indexer.confirmations = 0
        self.assertEqual(erc20_events_indexer.start(), (0, 0))

        account = self.ethereum_test_account
        amount = 10
        erc20_contract = self.deploy_example_erc20(amount, account.address)

        safe_contract = SafeContractFactory()
        IndexingStatus.objects.set_erc20_721_indexing_status(0)
        tx_hash = self.ethereum_client.erc20.send_tokens(
            safe_contract.address, amount, erc20_contract.address, account.key
        )
        self.assertEqual(
            erc20_events_indexer.start(),
            (1, self.ethereum_client.current_block_number + 1),
        )
        self.assertEqual(len(ERC20Transfer.objects.all()), 1)

        # Erc20/721 last indexed block number is stored on IndexingStatus
        self.assertGreater(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )
        block = EthereumBlock.objects.last()
        reorg_service.recover_from_reorg(block.number)

        self.assertEqual(len(ERC20Transfer.objects.all()), 0)
        with self.assertRaises(EthereumBlock.DoesNotExist):
            EthereumBlock.objects.get(number=block.number)

        erc20_events_indexer.start()

        self.assertIsNotNone(EthereumBlock.objects.get(number=block.number))
        self.assertEqual(len(ERC20Transfer.objects.all()), 1)
