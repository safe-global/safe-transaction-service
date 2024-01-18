from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth.clients import BlockscoutClient, EtherscanClient, SourcifyClient
from gnosis.eth.ethereum_client import EthereumClient, EthereumNetwork

from ...services.contract_metadata_service import get_contract_metadata_service
from ..mocks.contract_metadata_mocks import (
    blockscout_metadata_mock,
    etherscan_metadata_mock,
    sourcify_metadata_mock,
)


class TestContractAbi(TestCase):
    def setUp(self):
        super().setUp()
        with mock.patch.object(
            EthereumClient, "get_network", return_value=EthereumNetwork.GNOSIS
        ):
            # Setup service using Gnosis chain network so Sourcify, Etherscan and Blockscout clients are available
            get_contract_metadata_service.cache_clear()
            self.contract_metadata_service = get_contract_metadata_service()

    def tearDown(self):
        super().tearDown()
        get_contract_metadata_service.cache_clear()

    def test_singleton(self):
        self.assertEqual(
            get_contract_metadata_service(), self.contract_metadata_service
        )
        self.assertEqual(
            get_contract_metadata_service(), get_contract_metadata_service()
        )

    @mock.patch.object(EtherscanClient, "get_contract_metadata", autospec=True)
    @mock.patch.object(BlockscoutClient, "get_contract_metadata", autospec=True)
    @mock.patch.object(
        SourcifyClient, "is_chain_supported", autospec=True, return_value=True
    )
    @mock.patch.object(SourcifyClient, "get_contract_metadata", autospec=True)
    def test_get_contract_metadata(
        self,
        sourcify_get_contract_metadata_mock: MagicMock,
        sourcify_is_chain_supported: MagicMock,
        blockscout_get_contract_metadata_mock: MagicMock,
        etherscan_get_contract_metadata_mock: MagicMock,
    ):
        etherscan_get_contract_metadata_mock.return_value = etherscan_metadata_mock
        sourcify_get_contract_metadata_mock.return_value = sourcify_metadata_mock
        blockscout_get_contract_metadata_mock.return_value = blockscout_metadata_mock

        random_address = Account.create().address
        self.assertEqual(
            self.contract_metadata_service.get_contract_metadata(random_address),
            sourcify_metadata_mock,
        )
        sourcify_get_contract_metadata_mock.return_value = None
        self.assertEqual(
            self.contract_metadata_service.get_contract_metadata(random_address),
            etherscan_metadata_mock,
        )
        etherscan_get_contract_metadata_mock.side_effect = IOError
        self.assertEqual(
            self.contract_metadata_service.get_contract_metadata(random_address),
            blockscout_metadata_mock,
        )

        blockscout_get_contract_metadata_mock.side_effect = IOError
        self.assertIsNone(
            self.contract_metadata_service.get_contract_metadata(random_address)
        )
