from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from safe_eth.eth import EthereumClient

from ..models import (
    EthereumBlock,
    EthereumTx,
    IndexingStatus,
    MultisigTransaction,
    ProxyFactory,
    SafeMasterCopy,
)
from ..services import ReorgServiceProvider
from .factories import (
    EthereumBlockFactory,
    EthereumTxFactory,
    MultisigTransactionFactory,
    ProxyFactoryFactory,
    SafeMasterCopyFactory,
)
from .mocks.mocks_internal_tx_indexer import block_child, block_parent


class TestReorgService(TestCase):
    def setUp(self):
        ReorgServiceProvider.del_singleton()
        self.reorg_service = ReorgServiceProvider()

    def tearDown(self):
        ReorgServiceProvider.del_singleton()

    @mock.patch.object(EthereumClient, "get_blocks")
    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_check_reorgs(
        self, current_block_number_mock: PropertyMock, get_blocks_mock: MagicMock
    ):
        block = block_child
        block_number = block["number"]

        get_blocks_mock.return_value = [block_child, block_parent]
        current_block_number = block_number + 100
        current_block_number_mock.return_value = current_block_number

        ethereum_block: EthereumBlock = EthereumBlockFactory(
            number=block_number, confirmed=False
        )
        self.assertEqual(self.reorg_service.check_reorgs(), block_number)

        ethereum_block.block_hash = block["hash"]
        ethereum_block.save(update_fields=["block_hash"])
        self.assertIsNone(self.reorg_service.check_reorgs())
        ethereum_block.refresh_from_db()
        self.assertTrue(ethereum_block.confirmed)

    def test_reset_all_to_block(self):
        elements = 3
        for i in range(elements):
            ProxyFactoryFactory(tx_block_number=100 * i)
            SafeMasterCopyFactory(tx_block_number=300 * i)

        reorg_block_number = 5
        self.reorg_service.reset_all_to_block(reorg_block_number)

        # IndexingStatus will not be reset as block is lower than reorg block
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            0,
        )
        self.assertEqual(
            ProxyFactory.objects.filter(tx_block_number=reorg_block_number).count(),
            elements - 1,
        )
        self.assertEqual(
            SafeMasterCopy.objects.filter(tx_block_number=reorg_block_number).count(),
            elements - 1,
        )

        IndexingStatus.objects.set_erc20_721_indexing_status(reorg_block_number + 2)
        self.reorg_service.reset_all_to_block(reorg_block_number)
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            reorg_block_number,
        )

    def test_recover_from_reorg(self):
        reorg_block = 2_000  # Test a reorg in block 2000
        ethereum_blocks = [
            EthereumBlockFactory(number=block_number)
            for block_number in (1_000, 1_500, 2_000, 2_500, 3_000)
        ]
        ethereum_txs = [
            EthereumTxFactory(block=ethereum_block)
            for ethereum_block in ethereum_blocks
        ]
        test_origin = {"name": "awesome Safe app"}
        multisig_transactions = [
            MultisigTransactionFactory(ethereum_tx=ethereum_tx, origin=test_origin)
            for ethereum_tx in ethereum_txs
        ]
        safe_tx_hashes = [
            multisig_transaction.safe_tx_hash
            for multisig_transaction in multisig_transactions
        ]
        self.assertEqual(EthereumTx.objects.count(), len(ethereum_blocks))
        self.assertEqual(MultisigTransaction.objects.count(), len(ethereum_txs))

        # Set initial block number index status
        indexing_erc20_721_status = reorg_block - 500
        IndexingStatus.objects.set_erc20_721_indexing_status(
            indexing_erc20_721_status
        )  # Shouldn't be updated
        master_copies_status = reorg_block + 500
        safe_master_copy = SafeMasterCopyFactory(
            tx_block_number=master_copies_status
        )  # Should be updated
        proxy_factory = ProxyFactoryFactory(tx_block_number=reorg_block)

        self.reorg_service.recover_from_reorg(reorg_block)

        # Check that blocks and ethereum txs were deleted
        self.assertEqual(EthereumBlock.objects.count(), 2)
        self.assertEqual(
            EthereumBlock.objects.filter(number__gte=reorg_block).count(), 0
        )
        self.assertEqual(EthereumTx.objects.count(), 2)

        # Check that indexer rewound needed blocks
        expected_rewind_block = reorg_block - self.reorg_service.eth_reorg_rewind_blocks
        indexing_status = IndexingStatus.objects.get_erc20_721_indexing_status()
        safe_master_copy.refresh_from_db()
        proxy_factory.refresh_from_db()
        self.assertEqual(proxy_factory.tx_block_number, expected_rewind_block)
        self.assertEqual(indexing_status.block_number, indexing_erc20_721_status)
        self.assertEqual(safe_master_copy.tx_block_number, expected_rewind_block)
        after_reorg_multisigtransactions = MultisigTransaction.objects.filter(
            safe_tx_hash__in=safe_tx_hashes
        ).order_by("created")
        self.assertEqual(
            len(multisig_transactions), len(after_reorg_multisigtransactions)
        )

        # Transactions of previous blocks remains unchanged
        for (
            previous_reorg_multisig_transaction,
            after_reorg_multisig_transaction,
        ) in zip(
            multisig_transactions[:2],
            after_reorg_multisigtransactions[:2],
            strict=False,
        ):
            self.assertEqual(
                previous_reorg_multisig_transaction.safe_tx_hash,
                after_reorg_multisig_transaction.safe_tx_hash,
            )
            self.assertEqual(
                previous_reorg_multisig_transaction.ethereum_tx,
                after_reorg_multisig_transaction.ethereum_tx,
            )
            self.assertEqual(
                previous_reorg_multisig_transaction.signatures,
                after_reorg_multisig_transaction.signatures,
            )
            self.assertEqual(after_reorg_multisig_transaction.origin, test_origin)

        # Transactions after reorg were updated correctly
        for multisig_transaction in after_reorg_multisigtransactions[2:]:
            self.assertIsNone(multisig_transaction.ethereum_tx)
            self.assertIsNone(multisig_transaction.signatures)
            self.assertEqual(multisig_transaction.origin, test_origin)
