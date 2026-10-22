# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

import requests
from eth_account import Account
from safe_eth.eth.clients import BlockscoutClient, ContractMetadata, SourcifyClient
from safe_eth.eth.ethereum_client import EthereumClient, EthereumNetwork

from ...services.contract_metadata_service import get_contract_metadata_service
from ..mocks.contract_metadata_mocks import (
    blockscout_metadata_mock,
    sourcify_metadata_mock,
)


class TestContractAbi(TestCase):
    def setUp(self):
        super().setUp()
        with mock.patch.object(
            EthereumClient, "get_network", return_value=EthereumNetwork.GNOSIS
        ):
            # Setup service using Gnosis chain network so Sourcify and Blockscout clients are available
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
    ):
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
            blockscout_metadata_mock,
        )

        blockscout_get_contract_metadata_mock.side_effect = IOError
        self.assertIsNone(
            self.contract_metadata_service.get_contract_metadata(random_address)
        )

    @mock.patch.object(
        SourcifyClient, "is_chain_supported", autospec=True, return_value=True
    )
    def test_get_contract_metadata_client_errors(
        self, sourcify_is_chain_supported: MagicMock
    ):
        """
        A rate limited or failing client must not break metadata retrieval: the
        next enabled client is used, and ``None`` is returned if all of them fail
        """
        get_contract_metadata_service.cache_clear()
        with mock.patch.object(
            EthereumClient, "get_network", return_value=EthereumNetwork.GNOSIS
        ):
            contract_metadata_service = get_contract_metadata_service()
        sourcify_client = contract_metadata_service.sourcify_client
        blockscout_client = contract_metadata_service.blockscout_client
        self.assertEqual(
            contract_metadata_service.enabled_clients,
            [sourcify_client, blockscout_client],
        )

        rate_limited_response = MagicMock(ok=False, status_code=429)
        blockscout_response = MagicMock(ok=True, status_code=200)
        blockscout_response.json.return_value = {
            "name": "Blockscout Contract",
            "abi": blockscout_metadata_mock.abi,
            "implementations": [],
        }
        expected = ContractMetadata(
            "Blockscout Contract", blockscout_metadata_mock.abi, False, None
        )
        random_address = Account.create().address

        with (
            mock.patch.object(
                sourcify_client.http_session, "get", return_value=rate_limited_response
            ) as sourcify_get_mock,
            mock.patch.object(
                blockscout_client.http_session, "get", return_value=blockscout_response
            ),
        ):
            # Sourcify rate limited, falls back to Blockscout
            self.assertEqual(
                contract_metadata_service.get_contract_metadata(random_address),
                expected,
            )

            # Sourcify connection error, falls back to Blockscout
            sourcify_get_mock.side_effect = requests.exceptions.ConnectionError
            self.assertEqual(
                contract_metadata_service.get_contract_metadata(random_address),
                expected,
            )

        with (
            mock.patch.object(
                sourcify_client.http_session, "get", return_value=rate_limited_response
            ),
            mock.patch.object(
                blockscout_client.http_session,
                "get",
                return_value=rate_limited_response,
            ) as blockscout_get_mock,
        ):
            # Every client rate limited
            self.assertIsNone(
                contract_metadata_service.get_contract_metadata(random_address)
            )

            # Every client failing
            blockscout_get_mock.side_effect = requests.exceptions.Timeout
            self.assertIsNone(
                contract_metadata_service.get_contract_metadata(random_address)
            )
