from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth.clients import (
    BlockscoutClient,
    ContractMetadata,
    EtherscanClient,
    SourcifyClient,
)
from gnosis.eth.ethereum_client import EthereumClient, EthereumNetwork

from ...services.contract_metadata_service import get_contract_metadata_service


class TestContractAbi(TestCase):
    @mock.patch.object(EtherscanClient, "get_contract_metadata", autospec=True)
    @mock.patch.object(
        BlockscoutClient, "get_contract_metadata", autospec=True, side_effect=IOError
    )
    @mock.patch.object(
        SourcifyClient, "is_chain_supported", autospec=True, return_value=True
    )
    @mock.patch.object(SourcifyClient, "get_contract_metadata", autospec=True)
    def test_get_contract_metadata(
        self,
        sourcify_get_contract_metadata_mock: MagicMock,
        sourcify_is_chain_supported: MagicMock,
        blockscout_client_mock: MagicMock,
        etherscan_get_contract_metadata_mock: MagicMock,
    ):
        get_contract_metadata_service.cache_clear()
        with mock.patch.object(
            EthereumClient, "get_network", return_value=EthereumNetwork.MAINNET
        ):
            contract_metadata_service = get_contract_metadata_service()
        get_contract_metadata_service.cache_clear()

        etherscan_get_contract_metadata_mock.return_value = ContractMetadata(
            "Etherscan Uxio Contract",
            [
                {
                    "anonymous": False,
                    "inputs": [
                        {
                            "indexed": False,
                            "internalType": "address",
                            "name": "etherscanParam",
                            "type": "address",
                        }
                    ],
                    "name": "AddedOwner",
                    "type": "event",
                }
            ],
            False,
        )
        sourcify_get_contract_metadata_mock.return_value = ContractMetadata(
            "Sourcify Uxio Contract",
            [
                {
                    "anonymous": False,
                    "inputs": [
                        {
                            "indexed": False,
                            "internalType": "address",
                            "name": "sourcifyParam",
                            "type": "address",
                        }
                    ],
                    "name": "AddedOwner",
                    "type": "event",
                }
            ],
            False,
        )

        random_address = Account.create().address
        self.assertEqual(
            contract_metadata_service.get_contract_metadata(random_address),
            sourcify_get_contract_metadata_mock.return_value,
        )
        sourcify_get_contract_metadata_mock.return_value = None
        self.assertEqual(
            contract_metadata_service.get_contract_metadata(random_address),
            etherscan_get_contract_metadata_mock.return_value,
        )
        etherscan_get_contract_metadata_mock.return_value = None
        self.assertIsNone(
            contract_metadata_service.get_contract_metadata(random_address)
        )
