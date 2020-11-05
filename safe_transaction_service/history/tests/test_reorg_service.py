from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from gnosis.eth import EthereumClient

from ..models import (EthereumBlock, EthereumTx, ProxyFactory, SafeContract,
                      SafeMasterCopy)
from ..services import ReorgServiceProvider
from .factories import (EthereumBlockFactory, EthereumTxFactory,
                        ProxyFactoryFactory, SafeContractFactory,
                        SafeMasterCopyFactory)
from .mocks.mocks_internal_tx_indexer import block_result


class TestReorgService(TestCase):
    @mock.patch.object(EthereumClient, 'get_block', return_value=block_result[0])
    @mock.patch.object(EthereumClient, 'current_block_number', new_callable=PropertyMock)
    def test_check_reorgs(self, current_block_number_mock: PropertyMock, get_block_mock: MagicMock):
        reorg_service = ReorgServiceProvider()

        block = block_result[0]
        block_number = block['number']
        get_block_mock.return_value = block
        current_block_number = block_number + 100
        current_block_number_mock.return_value = current_block_number

        ethereum_block: EthereumBlock = EthereumBlockFactory(number=block_number, confirmed=False)
        self.assertEqual(reorg_service.check_reorgs(), block_number)

        ethereum_block.block_hash = block['hash']
        ethereum_block.save(update_fields=['block_hash'])
        self.assertIsNone(reorg_service.check_reorgs())
        ethereum_block.refresh_from_db()
        self.assertTrue(ethereum_block.confirmed)

    def test_reset_all_to_block(self):
        reorg_service = ReorgServiceProvider()

        elements = 3
        for i in range(elements):
            ProxyFactoryFactory(tx_block_number=100 * i)
            SafeContractFactory(erc20_block_number=200 * i)
            SafeMasterCopyFactory(tx_block_number=300 * i)

        block_number = 5
        reorg_service.reset_all_to_block(5)

        # All elements but 1 will be reset (with `tx_block_number=0` and `erc20_block_number=0`)
        self.assertEqual(ProxyFactory.objects.filter(tx_block_number=block_number).count(), elements - 1)
        self.assertEqual(SafeContract.objects.filter(erc20_block_number=block_number).count(), elements - 1)
        self.assertEqual(SafeMasterCopy.objects.filter(tx_block_number=block_number).count(), elements - 1)

    def test_recover_from_reorg(self):
        reorg_service = ReorgServiceProvider()

        reorg_block = 2000  # Test a reorg in block 2000
        ethereum_blocks = [EthereumBlockFactory(number=reorg_block + i) for i in range(-1000, 1001, 500)]
        ethereum_txs = [EthereumTxFactory(block=ethereum_block) for ethereum_block in ethereum_blocks]
        safe_ethereum_tx = ethereum_txs[0]  # This tx will not be touched by the reorg

        self.assertEqual(EthereumTx.objects.count(), len(ethereum_blocks))

        proxy_factory = ProxyFactoryFactory(tx_block_number=reorg_block)
        safe_contract = SafeContractFactory(erc20_block_number=reorg_block - 500,
                                            ethereum_tx=safe_ethereum_tx)
        safe_master_copy = SafeMasterCopyFactory(tx_block_number=reorg_block + 500)

        reorg_service.recover_from_reorg(reorg_block)

        # Check that blocks and ethereum txs were deleted
        self.assertEqual(EthereumBlock.objects.count(), 2)
        self.assertEqual(EthereumBlock.objects.filter(number__gte=reorg_block).count(), 0)
        self.assertEqual(EthereumTx.objects.count(), 2)

        # Check that indexer rewound needed blocks
        proxy_factory.refresh_from_db()
        self.assertEqual(proxy_factory.tx_block_number, reorg_block - reorg_service.eth_reorg_rewind_blocks)
        safe_contract.refresh_from_db()
        self.assertEqual(safe_contract.erc20_block_number, reorg_block - 500)
        safe_master_copy.refresh_from_db()
        self.assertEqual(safe_master_copy.tx_block_number, reorg_block - reorg_service.eth_reorg_rewind_blocks)
