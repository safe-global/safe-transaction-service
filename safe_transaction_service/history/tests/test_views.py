import datetime
import json
import logging
from unittest import mock
from unittest.mock import MagicMock
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

import eth_abi
from eth_account import Account
from factory.fuzzy import FuzzyText
from hexbytes import HexBytes
from requests import ReadTimeout
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.ethereum_client import EthereumClient, TracingManager
from safe_eth.eth.utils import fast_is_checksum_address, fast_keccak_text
from safe_eth.safe import CannotEstimateGas, Safe, SafeOperationEnum
from safe_eth.safe.safe_signature import SafeSignature, SafeSignatureType
from safe_eth.safe.signatures import signature_to_bytes
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.account_abstraction.tests import factories as aa_factories
from safe_transaction_service.contracts.models import ContractQuerySet
from safe_transaction_service.contracts.tests.factories import ContractFactory
from safe_transaction_service.contracts.tx_decoder import DbTxDecoder
from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.tests.factories import TokenFactory
from safe_transaction_service.utils.utils import datetime_to_str

from ...utils.redis import get_redis
from ..helpers import DelegateSignatureHelper, DeleteMultisigTxSignatureHelper
from ..models import (
    IndexingStatus,
    InternalTx,
    InternalTxType,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContractDelegate,
    SafeMasterCopy,
)
from ..serializers import TransferType
from ..views import (
    SafeModuleTransactionListView,
    SafeMultisigTransactionListView,
    SafeTransferListView,
)
from .factories import (
    ERC20TransferFactory,
    ERC721TransferFactory,
    EthereumTxFactory,
    InternalTxFactory,
    ModuleTransactionFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
    SafeStatusFactory,
)
from .mocks.blocks import mocked_blocks
from .mocks.deployments_mock import (
    mainnet_deployments,
    mainnet_deployments_1_4_1,
    mainnet_deployments_1_4_1_multisend,
    mainnet_deployments_1_4_1_safe,
)
from .mocks.mocks_safe_creation import (
    create_cpk_test_data,
    create_test_data_v1_0_0,
    create_test_data_v1_1_1,
    create_v1_4_1_test_data,
    data_decoded_cpk,
    data_decoded_v1_0_0,
    data_decoded_v1_1_1,
    data_decoded_v1_4_1,
)
from .mocks.traces import call_trace

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def setUp(self):
        get_redis().flushall()

    def tearDown(self):
        get_redis().flushall()

    def test_about_view(self):
        url = reverse("v1:history:about")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_swagger_json_schema(self):
        url = reverse("schema-json") + "?format=json"
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_swagger_ui(self):
        url = reverse("schema-swagger-ui")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_about_ethereum_rpc_url(self):
        for url_name in (
            "v1:history:about-ethereum-rpc",
            "v1:history:about-ethereum-tracing-rpc",
        ):
            with self.subTest(url_name=url_name):
                url = reverse(url_name)
                response = self.client.get(url, format="json")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("EthereumJS TestRPC", response.data["version"])
                self.assertGreaterEqual(response.data["block_number"], 0)
                self.assertEqual(response.data["chain_id"], 1337)
                self.assertEqual(response.data["chain"], "GANACHE")
                self.assertEqual(response.data["syncing"], False)

    @mock.patch.object(
        EthereumClient,
        "get_block",
        return_value=mocked_blocks[0],
    )
    @mock.patch.object(
        EthereumClient,
        "get_blocks",
        return_value=mocked_blocks[1:],
    )
    def test_indexing_view(self, mock_get_blocks: MagicMock, mock_get_block: MagicMock):
        IndexingStatus.objects.set_erc20_721_indexing_status(2_005)
        url = reverse("v1:history:indexing")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2_000)
        self.assertEqual(response.data["erc20_block_number"], 2_000)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 2_000)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], True)
        # Same block, so they should share the same timestamp
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:23Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:23Z"
        )

        IndexingStatus.objects.set_erc20_721_indexing_status(500)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 499)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 2000)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        safe_master_copy = SafeMasterCopyFactory(tx_block_number=2000)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 499)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 1999)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        safe_master_copy.tx_block_number = 600
        safe_master_copy.save(update_fields=["tx_block_number"])
        response = self.client.get(url, format="json")
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 499)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 599)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        IndexingStatus.objects.set_erc20_721_indexing_status(10)
        SafeMasterCopyFactory(tx_block_number=8)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 9)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 7)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        SafeMasterCopyFactory(tx_block_number=11)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 9)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 7)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        IndexingStatus.objects.set_erc20_721_indexing_status(2_000)
        SafeMasterCopy.objects.update(tx_block_number=2_000)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 1999)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 1999)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], True)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

        SafeMasterCopyFactory(tx_block_number=48)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 1999)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 47)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)
        self.assertEqual(
            response.data["current_block_timestamp"], "2024-06-03T18:29:23Z"
        )
        self.assertEqual(response.data["erc20_block_timestamp"], "2024-06-03T18:29:35Z")
        self.assertEqual(
            response.data["master_copies_block_timestamp"], "2024-06-03T18:29:47Z"
        )

    # Mock chain id to mainnet
    @mock.patch("safe_transaction_service.history.views.get_chain_id", return_value=1)
    def test_safe_deployments_view(self, get_chain_id_mock):
        url = reverse("v1:history:deployments")
        response = self.client.get(url, format="json")
        self.maxDiff = None
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), mainnet_deployments)

        response = self.client.get(url + "?version=5.0.0", format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(url + "?version=1.4.1", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [mainnet_deployments_1_4_1])

        response = self.client.get(
            url + "?version=1.4.1&contract=MultiSend", format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [{"version": "1.4.1", "contracts": [mainnet_deployments_1_4_1_multisend]}],
        )

        response = self.client.get(url + "?contract=Safe", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [
                {"version": "1.0.0", "contracts": []},
                {"version": "1.1.1", "contracts": []},
                {"version": "1.2.0", "contracts": []},
                {"version": "1.3.0", "contracts": []},
                {"version": "1.4.1", "contracts": [mainnet_deployments_1_4_1_safe]},
            ],
        )

    def test_all_transactions_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(
            _from=safe_address, value=5
        )  # Should not appear
        erc20_transfer_in = ERC20TransferFactory(to=safe_address)
        erc20_transfer_out = ERC20TransferFactory(_from=safe_address)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = (
            MultisigTransactionFactory()
        )  # Should not appear, it's for another Safe

        # Should not appear as they are not executed
        for _ in range(2):
            MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)
        transfers_not_empty = [
            False,  # Multisig transaction, no transfer
            True,  # Erc transfer out
            True,  # Erc transfer in
            True,  # internal tx in
            False,  # Module transaction
            False,  # Multisig transaction
        ]
        for transfer_not_empty, transaction in zip(
            transfers_not_empty, response.data["results"]
        ):
            self.assertEqual(bool(transaction["transfers"]), transfer_not_empty)
            self.assertTrue(transaction["tx_type"])

        # Test pagination
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,)) + "?limit=3"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 3)
        self.assertIsInstance(response.data["results"][0]["nonce"], int)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?limit=4&offset=4"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 2)

        # Add transfer out for the module transaction and transfer in for the multisig transaction
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address, ethereum_tx=module_transaction.internal_tx.ethereum_tx
        )
        # Add token info for that transfer
        token = TokenFactory(address=erc20_transfer_out.address)
        internal_tx_in = InternalTxFactory(
            to=safe_address, value=8, ethereum_tx=multisig_transaction.ethereum_tx
        )
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)
        self.assertEqual(
            response.data["results"][4]["transfers"][0]["token_info"],
            {
                "type": "ERC20",
                "address": token.address,
                "name": token.name,
                "symbol": token.symbol,
                "decimals": token.decimals,
                "logo_uri": token.get_full_logo_uri(),
                "trusted": token.trusted,
            },
        )
        transfers_not_empty = [
            False,  # Multisig transaction, no transfer
            True,  # Erc transfer out
            True,  # Erc transfer in
            True,  # internal tx in
            True,  # Module transaction
            True,  # Multisig transaction
        ]
        for transfer_not_empty, transaction in zip(
            transfers_not_empty, response.data["results"]
        ):
            self.assertEqual(bool(transaction["transfers"]), transfer_not_empty)

    def test_all_transactions_executed(self):
        safe_address = Account.create().address

        # No mined
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        # Mined
        MultisigTransactionFactory(safe=safe_address)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_all_transactions_ordering(self):
        safe_address = Account.create().address

        # Older transaction
        erc20_transfer = ERC20TransferFactory(to=safe_address)
        # Newer transaction
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)

        # Nonce is not allowed as a sorting parameter
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?ordering=nonce"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # By default, newer transactions first
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["results"][0]["transaction_hash"],
            multisig_transaction.ethereum_tx_id,
        )
        self.assertEqual(
            response.data["results"][1]["tx_hash"], erc20_transfer.ethereum_tx_id
        )
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?ordering=timestamp"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["results"][0]["tx_hash"], erc20_transfer.ethereum_tx_id
        )
        self.assertEqual(
            response.data["results"][1]["transaction_hash"],
            multisig_transaction.ethereum_tx_id,
        )

    def test_all_transactions_wrong_transfer_type_view(self):
        # No token in database, so we must trust the event
        safe_address = Account.create().address
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address
        )  # ERC20 event (with `value`)
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["value"])

        # Result should be the same, as we are adding an ERC20 token
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["value"])

        # Result should change if we set the token as an ERC721
        token.decimals = None
        token.save(update_fields=["decimals"])
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC721_TRANSFER.name,
        )
        # TokenId and Value must be swapped now
        self.assertIsNone(response.data["results"][0]["transfers"][0]["value"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["token_id"])

        # It should work with value=0
        safe_address = Account.create().address
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address, value=0
        )  # ERC20 event (with `value`)
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertEqual(response.data["results"][0]["transfers"][0]["value"], "0")

    def test_all_transactions_duplicated_multisig_tx_view(self):
        """
        Test 2 module transactions with the same tx_hash
        """
        safe_address = Account.create().address
        multisig_transaction_1 = MultisigTransactionFactory(safe=safe_address)
        multisig_transaction_2 = MultisigTransactionFactory(
            safe=safe_address,
            ethereum_tx=multisig_transaction_1.ethereum_tx,
        )

        self.assertEqual(
            multisig_transaction_1.ethereum_tx,
            multisig_transaction_2.ethereum_tx,
        )

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        # We are aware of this. Pagination is done by `tx_hash`, so 2 transactions
        # with the same `tx_hash` will return a `count` of 1
        self.assertEqual(response.data["count"], 1)
        # Even if they have the same `tx_hash`, tx with higher nonce will come first
        self.assertEqual(
            [multisig_transaction_2.safe_tx_hash, multisig_transaction_1.safe_tx_hash],
            [multisig_tx["safe_tx_hash"] for multisig_tx in response.data["results"]],
        )

    def test_all_transactions_duplicated_module_view(self):
        """
        Test 2 module transactions with the same tx_hash
        """
        safe_address = Account.create().address
        module_transaction_1 = ModuleTransactionFactory(safe=safe_address)
        module_transaction_2 = ModuleTransactionFactory(
            safe=safe_address,
            internal_tx__ethereum_tx=module_transaction_1.internal_tx.ethereum_tx,
        )

        self.assertEqual(
            module_transaction_1.internal_tx.ethereum_tx,
            module_transaction_2.internal_tx.ethereum_tx,
        )

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        # We are aware of this. Pagination is done by `tx_hash`, so 2 transactions
        # with the same `tx_hash` will return a `count` of 1
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            {module_transaction_1.module, module_transaction_2.module},
            {module_tx["module"] for module_tx in response.data["results"]},
        )

    def test_get_module_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:module-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        module_transaction = ModuleTransactionFactory(safe=safe_address)
        response = self.client.get(
            reverse("v1:history:module-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["safe"], module_transaction.safe)
        self.assertEqual(
            response.data["results"][0]["module"], module_transaction.module
        )
        self.assertEqual(
            response.data["results"][0]["is_successful"], not module_transaction.failed
        )

        # Add another ModuleTransaction to check filters
        ModuleTransactionFactory(safe=safe_address)

        url = (
            reverse("v1:history:module-transactions", args=(safe_address,))
            + f"?transaction_hash={module_transaction.internal_tx.ethereum_tx_id}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        url = (
            reverse("v1:history:module-transactions", args=(safe_address,))
            + "?transaction_hash=0x2345"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        url = (
            reverse("v1:history:module-transactions", args=(safe_address,))
            + f"?block_number={module_transaction.internal_tx.ethereum_tx.block_id}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        # Test that the result should be cached
        # Mock get_queryset with empty queryset return value to get proper error in case of fail
        with mock.patch.object(
            SafeModuleTransactionListView,
            "get_queryset",
            return_value=ModuleTransaction.objects.none(),
        ) as patched_queryset:
            response = self.client.get(url, format="json")
            # queryset shouldn't be called
            patched_queryset.assert_not_called()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)

    def test_get_module_transaction(self):
        wrong_module_transaction_id = "wrong_module_transaction_id"
        url = reverse(
            "v1:history:module-transaction", args=(wrong_module_transaction_id,)
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        no_exist_module_transaction_id = (
            "ief060441f0101ab83d62066b962f97e3a582686e0720157407c965c5946c2f7a0"
        )
        url = reverse(
            "v1:history:module-transaction", args=(no_exist_module_transaction_id,)
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        safe_address = Account.create().address
        ethereum_tx_hash = (
            "0xef060441f0101ab83d62066b962f97e3a582686e0720157407c965c5946c2f7a"
        )
        ethereum_tx = EthereumTxFactory(tx_hash=ethereum_tx_hash)
        internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx, trace_address="0,0,0,0"
        )
        module_transaction = ModuleTransactionFactory(
            internal_tx=internal_tx, safe=safe_address
        )
        module_transaction_id = (
            "ief060441f0101ab83d62066b962f97e3a582686e0720157407c965c5946c2f7a0,0,0,0"
        )
        url = reverse("v1:history:module-transaction", args=(module_transaction_id,))
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(module_transaction.created),
                "executionDate": datetime_to_str(
                    module_transaction.internal_tx.ethereum_tx.block.timestamp
                ),
                "blockNumber": module_transaction.internal_tx.ethereum_tx.block_id,
                "isSuccessful": not module_transaction.failed,
                "transactionHash": module_transaction.internal_tx.ethereum_tx_id,
                "safe": safe_address,
                "module": module_transaction.module,
                "to": module_transaction.to,
                "value": str(module_transaction.value),
                "data": to_0x_hex_str(module_transaction.data),
                "operation": module_transaction.operation,
                "dataDecoded": None,
                "moduleTransactionId": module_transaction_id,
            },
        )

    def test_get_multisig_confirmation(self):
        random_safe_tx_hash = to_0x_hex_str(fast_keccak_text("enxebre"))
        response = self.client.get(
            reverse(
                "v1:history:multisig-transaction-confirmations",
                args=(random_safe_tx_hash,),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        multisig_confirmation_1 = MultisigConfirmationFactory()
        MultisigConfirmationFactory(
            multisig_transaction=multisig_confirmation_1.multisig_transaction
        )
        safe_tx_hash = multisig_confirmation_1.multisig_transaction_id
        response = self.client.get(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_post_multisig_confirmation(self):
        random_safe_tx_hash = to_0x_hex_str(fast_keccak_text("enxebre"))
        data = {
            "signature": to_0x_hex_str(
                Account.create().unsafe_sign_hash(random_safe_tx_hash)["signature"]
            )  # Not valid signature
        }
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations",
                args=(random_safe_tx_hash,),
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("was not found", response.data["detail"])

        owner_account_1 = Account.create()
        owner_account_2 = Account.create()
        safe = self.deploy_test_safe(
            owners=[owner_account_1.address, owner_account_2.address]
        )
        safe_address = safe.address
        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address, trusted=False
        )
        safe_tx_hash = multisig_transaction.safe_tx_hash
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
            data={},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        random_account = Account.create()
        data = {
            "signature": to_0x_hex_str(
                random_account.unsafe_sign_hash(safe_tx_hash)["signature"]
            )  # Not valid signature
        }
        # Transaction was executed, confirmations cannot be added
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            f"Transaction with safe-tx-hash={safe_tx_hash} was already executed",
            response.data["signature"][0],
        )

        # Mark transaction as not executed, signature is still not valid
        multisig_transaction.ethereum_tx = None
        multisig_transaction.save(update_fields=["ethereum_tx"])
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            f"Signer={random_account.address} is not an owner",
            response.data["signature"][0],
        )

        data = {
            "signature": to_0x_hex_str(
                owner_account_1.unsafe_sign_hash(safe_tx_hash)["signature"]
            )
        }
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)
        modified = multisig_transaction.modified
        multisig_transaction.refresh_from_db()
        self.assertTrue(multisig_transaction.trusted)
        self.assertGreater(
            multisig_transaction.modified, modified
        )  # Modified should be updated

        # Add multiple signatures
        data = {
            "signature": to_0x_hex_str(
                owner_account_1.unsafe_sign_hash(safe_tx_hash)["signature"]
                + owner_account_2.unsafe_sign_hash(safe_tx_hash)["signature"]
            )
        }
        self.assertEqual(MultisigConfirmation.objects.count(), 1)
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations", args=(safe_tx_hash,)
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 2)

    def test_post_multisig_confirmation_banned(self):
        owner_account_1 = Account.create()
        owner_account_2 = Account.create()
        safe = self.deploy_test_safe(
            owners=[owner_account_1.address, owner_account_2.address]
        )
        safe_address = safe.address
        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address, trusted=True, ethereum_tx=None
        )
        safe_tx_hash = multisig_transaction.safe_tx_hash
        data = {
            "signature": to_0x_hex_str(
                owner_account_1.unsafe_sign_hash(safe_tx_hash)["signature"]
            )
        }
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        with self.settings(BANNED_EOAS={owner_account_1.address}):
            response = self.client.post(
                reverse(
                    "v1:history:multisig-transaction-confirmations",
                    args=(safe_tx_hash,),
                ),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "signature": [
                        f"Signer={owner_account_1.address} is not authorized to interact with the service"
                    ]
                },
            )
            self.assertEqual(MultisigConfirmation.objects.count(), 0)

    def test_get_multisig_transaction(self):
        safe = self.deploy_test_safe()
        safe_address = safe.address
        safe_tx_hash = to_0x_hex_str(fast_keccak_text("gnosis"))
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        add_owner_with_threshold_data = HexBytes(
            "0x0d582f130000000000000000000000001b9a0da11a5cace4e7035993cbb2e4"
            "b1b3b164cf000000000000000000000000000000000000000000000000000000"
            "0000000001"
        )

        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, data=add_owner_with_threshold_data
        )
        safe_tx_hash = multisig_tx.safe_tx_hash
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["confirmations"]), 0)
        self.assertTrue(fast_is_checksum_address(response.data["executor"]))
        self.assertEqual(
            response.data["transaction_hash"], multisig_tx.ethereum_tx.tx_hash
        )
        self.assertEqual(response.data["origin"], multisig_tx.origin)
        self.assertFalse(response.data["trusted"])
        self.assertIsNone(response.data["max_fee_per_gas"])
        self.assertIsNone(response.data["max_priority_fee_per_gas"])
        self.assertIsNone(response.data["proposer"])
        self.assertIsNone(response.data["proposed_by_delegate"])
        self.assertIsInstance(response.data["nonce"], int)

        self.assertEqual(
            response.data["data_decoded"],
            {
                "method": "addOwnerWithThreshold",
                "parameters": [
                    {
                        "name": "owner",
                        "type": "address",
                        "value": "0x1b9a0DA11a5caCE4e703599" "3Cbb2E4B1B3b164Cf",
                    },
                    {"name": "_threshold", "type": "uint256", "value": "1"},
                ],
            },
        )

        # Test camelCase
        self.assertEqual(
            response.json()["transactionHash"], multisig_tx.ethereum_tx.tx_hash
        )
        # Test empty origin object
        multisig_tx.origin = {}
        multisig_tx.save(update_fields=["origin"])
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["origin"], json.dumps({}))
        self.assertEqual(json.loads(response.data["origin"]), {})

        # Test origin object
        origin = {"app": "Testing App", "name": "Testing"}
        multisig_tx.origin = origin
        multisig_tx.save(update_fields=["origin"])
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["origin"], json.dumps(origin))
        self.assertEqual(json.loads(response.data["origin"]), origin)

        # Test proposer
        proposer = Account.create().address
        multisig_tx.proposer = proposer
        multisig_tx.save()
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.data["proposer"], proposer)

        # Check proposed_by_delegate
        delegate = Account.create().address
        multisig_tx.proposed_by_delegate = delegate
        multisig_tx.save()
        response = self.client.get(
            reverse("v1:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.data["proposer"], proposer)
        self.assertEqual(response.data["proposed_by_delegate"], delegate)

    def test_delete_multisig_transaction(self):
        owner_account = Account.create()
        safe_tx_hash = to_0x_hex_str(fast_keccak_text("random-tx"))
        url = reverse("v1:history:multisig-transaction", args=(safe_tx_hash,))
        data = {"signature": "0x" + "1" * (130 * 2)}  # 2 signatures of 65 bytes
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Add our test MultisigTransaction to the database
        safe = SafeContractFactory()
        multisig_transaction = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash, safe=safe.address
        )

        # Add other MultisigTransactions to the database to make sure they are not deleted
        MultisigTransactionFactory()
        MultisigTransactionFactory()

        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Executed transactions cannot be deleted", code="invalid"
                    )
                ]
            },
        )

        multisig_transaction.ethereum_tx = None
        multisig_transaction.save(update_fields=["ethereum_tx"])
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Old transactions without proposer cannot be deleted",
                        code="invalid",
                    )
                ]
            },
        )

        # Set a random proposer for the transaction
        multisig_transaction.proposer = Account.create().address
        multisig_transaction.save(update_fields=["proposer"])
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="1 owner signature was expected, 2 received",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a contract signature
        data = {"signature": "0x" + "0" * 130}  # 1 signature of 65 bytes
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Only EOA and ETH_SIGN signatures are supported",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a real not valid signature and set the right proposer
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.save(update_fields=["proposer"])
        data = {
            "signature": to_0x_hex_str(
                owner_account.unsafe_sign_hash(safe_tx_hash)["signature"]
            )  # Random signature
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Calculate a valid message_hash
        message_hash = DeleteMultisigTxSignatureHelper.calculate_hash(
            safe.address,
            safe_tx_hash,
            self.ethereum_client.get_chain_id(),
            previous_totp=False,
        )

        # Use an expired user delegate
        safe_delegate = Account.create()
        safe_contract_delegate = SafeContractDelegateFactory(
            safe_contract_id=multisig_transaction.safe,
            delegate=safe_delegate.address,
            delegator=owner_account.address,
            expiry_date=timezone.now() - datetime.timedelta(minutes=1),
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a deleted user delegate
        safe_contract_delegate.delete()
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a proper signature of an user delegate
        SafeContractDelegateFactory(
            safe_contract_id=multisig_transaction.safe,
            delegate=safe_delegate.address,
            delegator=owner_account.address,
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertTrue(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertFalse(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )

        # Use a proper signature of a proposer user
        multisig_transaction = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash, safe=safe.address, ethereum_tx=None
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.save(update_fields=["proposer"])
        data = {
            "signature": to_0x_hex_str(
                owner_account.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertTrue(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertFalse(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )

        # Trying to do the query again should raise a 404
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_multisig_transactions(self):
        safe = self.deploy_test_safe()
        safe_address = safe.address
        proposer = safe.retrieve_owners()[0]
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["count_unique_nonce"], 0)

        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, proposer=proposer, trusted=True
        )
        # Not trusted multisig transaction should not be returned by default
        MultisigTransactionFactory(safe=safe_address, proposer=proposer, trusted=False)
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["count_unique_nonce"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 0)
        self.assertTrue(
            fast_is_checksum_address(response.data["results"][0]["executor"])
        )
        self.assertEqual(
            response.data["results"][0]["transaction_hash"],
            multisig_tx.ethereum_tx.tx_hash,
        )
        self.assertIsInstance(response.data["results"][0]["nonce"], int)
        # Test camelCase
        self.assertEqual(
            response.json()["results"][0]["transactionHash"],
            multisig_tx.ethereum_tx.tx_hash,
        )
        # Check Etag header
        self.assertTrue(response["Etag"])
        MultisigConfirmationFactory(multisig_transaction=multisig_tx)
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 1)
        self.assertEqual(response.data["results"][0]["proposer"], proposer)
        self.assertIsNone(response.data["results"][0]["proposed_by_delegate"])

        # Check proposed_by_delegate
        delegate = Account.create().address
        multisig_tx.proposed_by_delegate = delegate
        multisig_tx.save()
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["proposer"], proposer)
        self.assertEqual(response.data["results"][0]["proposed_by_delegate"], delegate)

        # Check not trusted
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?trusted=False",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

        MultisigTransactionFactory(
            safe=safe_address, nonce=multisig_tx.nonce, trusted=True
        )
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["count_unique_nonce"], 1)

        #
        # Mock get_queryset with empty queryset return value to get proper error in case of fail
        with mock.patch.object(
            SafeMultisigTransactionListView,
            "get_queryset",
            return_value=MultisigTransaction.objects.none(),
        ) as patched_queryset:
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            # view shouldn't be called
            patched_queryset.assert_not_called()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 2)
            self.assertEqual(response.data["count_unique_nonce"], 1)

    def test_get_multisig_transactions_unique_nonce(self):
        """
        Unique nonce should follow the trusted filter
        """

        safe = self.deploy_test_safe()
        safe_address = safe.address
        url = reverse("v1:history:multisig-transactions", args=(safe_address,))
        response = self.client.get(
            url,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["count_unique_nonce"], 0)

        MultisigTransactionFactory(safe=safe_address, nonce=6, trusted=True)
        MultisigTransactionFactory(safe=safe_address, nonce=12, trusted=False)

        # Unique nonce ignores not trusted transactions by default
        response = self.client.get(
            url,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["count_unique_nonce"], 1)

        response = self.client.get(
            url + "?trusted=False",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["count_unique_nonce"], 2)

    @mock.patch.object(
        DbTxDecoder, "get_data_decoded", return_value={"param1": "value"}
    )
    def test_get_multisig_transactions_not_decoded(
        self, get_data_decoded_mock: MagicMock
    ):
        try:
            safe = self.deploy_test_safe()
            safe_address = safe.address
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            multisig_transaction = MultisigTransactionFactory(
                safe=safe_address,
                operation=SafeOperationEnum.CALL.value,
                data=b"abcd",
                trusted=True,
            )
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data["results"][0]["data_decoded"], {"param1": "value"}
            )

            multisig_transaction.operation = SafeOperationEnum.DELEGATE_CALL.value
            multisig_transaction.save()
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIsNone(response.data["results"][0]["data_decoded"])

            ContractFactory(
                address=multisig_transaction.to, trusted_for_delegate_call=True
            )
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            # Force don't use cache because we are not cleaning the cache on contracts change
            with mock.patch(
                "safe_transaction_service.history.views.settings.CACHE_VIEW_DEFAULT_TIMEOUT",
                0,
            ):
                response = self.client.get(
                    reverse("v1:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    response.data["results"][0]["data_decoded"], {"param1": "value"}
                )
        finally:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()

    def test_get_multisig_transactions_filters(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?nonce=0",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?to=0x2a",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["to"][0], "Enter a valid checksummed Ethereum Address."
        )

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + f"?to={multisig_transaction.to}",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?nonce=1",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?executed=true",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?executed=false",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?has_confirmations=True",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            force_sign_with_account=safe_owner_1,
        )
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,))
            + "?has_confirmations=True",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_post_multisig_transactions_null_signature(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
            "signature": None,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse(
                "v1:history:multisig-transaction",
                args=(data["contractTransactionHash"],),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["executor"])
        self.assertEqual(len(response.data["confirmations"]), 0)

    def test_post_multisig_transactions(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse(
                "v1:history:multisig-transaction",
                args=(data["contractTransactionHash"],),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["executor"])
        self.assertEqual(len(response.data["confirmations"]), 0)
        self.assertEqual(response.data["proposer"], data["sender"])
        self.assertIsNone(response.data["proposed_by_delegate"])

        # Test confirmation with signature
        data["signature"] = to_0x_hex_str(
            safe_owner_1.unsafe_sign_hash(safe_tx.safe_tx_hash)["signature"]
        )
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        modified = multisig_transaction_db.modified
        multisig_transaction_db.refresh_from_db()
        self.assertTrue(multisig_transaction_db.trusted)  # Now it should be trusted
        self.assertGreater(
            multisig_transaction_db.modified, modified
        )  # Modified should be updated

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 1)
        self.assertEqual(
            response.data["results"][0]["confirmations"][0]["signature"],
            data["signature"],
        )
        self.assertTrue(response.data["results"][0]["trusted"])

        # Sign with a different user that sender
        random_user_account = Account.create()
        data["signature"] = to_0x_hex_str(
            random_user_account.unsafe_sign_hash(safe_tx.safe_tx_hash)["signature"]
        )
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Signer={random_user_account.address} is not an owner",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Use random user as sender (not owner)
        del data["signature"]
        data["sender"] = random_user_account.address
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Sender={random_user_account.address} is not an owner",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_post_multisig_transaction_with_zero_to(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        data = {
            "to": NULL_ADDRESS,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

    def test_post_multisig_transaction_with_1271_signature(self):
        account = Account.create()
        safe_owner = self.deploy_test_safe(owners=[account.address])
        safe = self.deploy_test_safe(owners=[safe_owner.address])

        data = {
            "to": account.address,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            "sender": safe_owner.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        safe_tx_hash_preimage = safe_tx.safe_tx_hash_preimage

        safe_owner_message_hash = safe_owner.get_message_hash(safe_tx_hash_preimage)
        safe_owner_signature = account.unsafe_sign_hash(safe_owner_message_hash)[
            "signature"
        ]
        signature_1271 = (
            signature_to_bytes(
                0, int.from_bytes(HexBytes(safe_owner.address), byteorder="big"), 65
            )
            + eth_abi.encode(["bytes"], [safe_owner_signature])[32:]
        )

        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(signature_1271)

        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe.address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Ensure right response is returned
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe.address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        multisig_transaction_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx_hash
        )
        self.assertTrue(multisig_transaction_db.trusted)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

        # Test MultisigConfirmation endpoint
        confirmation_data = {"signature": data["signature"]}
        MultisigConfirmation.objects.all().delete()
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations",
                args=(to_0x_hex_str(safe_tx_hash),),
            ),
            format="json",
            data=confirmation_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

    def test_post_multisig_transaction_with_trusted_user(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address
        data = {
            "to": Account.create().address,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)

        factory = APIRequestFactory()
        request = factory.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        # Create user
        user = get_user_model().objects.create(
            username="batman", password="very-private"
        )
        request = factory.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        force_authenticate(request, user=user)
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        # Assign permissions to user
        permission = Permission.objects.get(codename="create_trusted")
        user.user_permissions.add(permission)
        request = factory.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        user = get_user_model().objects.get()  # Flush permissions cache
        force_authenticate(request, user=user)
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertTrue(multisig_transaction_db.trusted)

    def test_post_multisig_transaction_executed(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        multisig_transaction = MultisigTransaction.objects.first()
        multisig_transaction.ethereum_tx = EthereumTxFactory()
        multisig_transaction.save(update_fields=["ethereum_tx"])
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f'Tx with safe-tx-hash={data["contractTransactionHash"]} '
            f"for safe={safe.address} was already executed in "
            f"tx-hash={multisig_transaction.ethereum_tx_id}",
            response.data["non_field_errors"],
        )

        # Check another tx with same nonce
        data["to"] = Account.create().address
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Tx with nonce={safe_tx.safe_nonce} for safe={safe.address} "
            f"already executed in tx-hash={multisig_transaction.ethereum_tx_id}",
            response.data["non_field_errors"],
        )

        # Successfully insert tx with nonce=1
        data["nonce"] = 1
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_post_multisig_transactions_with_origin(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        origin_max_len = 200  # Origin field limit
        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
            "origin": "A" * (origin_max_len + 1),
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        data["origin"] = "A" * origin_max_len
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, data["origin"])
        data["origin"] = '{"url": "test", "name":"test"}'
        data["nonce"] = 1
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, json.loads(data["origin"]))

    def test_post_multisig_transactions_with_multiple_signatures(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe.address

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owners[0].address,
            "origin": "Testing origin field",
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(
            b"".join(
                [
                    safe_owner.unsafe_sign_hash(safe_tx_hash)["signature"]
                    for safe_owner in safe_owners
                ]
            )
        )
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, data["origin"])

        multisig_confirmations = MultisigConfirmation.objects.filter(
            multisig_transaction_hash=safe_tx_hash
        )
        self.assertEqual(len(multisig_confirmations), len(safe_owners))
        for multisig_confirmation in multisig_confirmations:
            safe_signatures = SafeSignature.parse_signature(
                multisig_confirmation.signature, safe_tx_hash
            )
            self.assertEqual(len(safe_signatures), 1)
            safe_signature = safe_signatures[0]
            self.assertEqual(safe_signature.signature_type, SafeSignatureType.EOA)
            self.assertIn(safe_signature.owner, safe_owner_addresses)
            safe_owner_addresses.remove(safe_signature.owner)

    def test_post_multisig_transactions_with_delegate(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe_delegate = Account.create()
        safe = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe.address

        self.assertEqual(MultisigTransaction.objects.count(), 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owners[0].address,
            "origin": "Testing origin field",
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(
            safe_delegate.unsafe_sign_hash(safe_tx_hash)["signature"]
        )

        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Signer={safe_delegate.address} is not an owner or delegate",
            response.data["non_field_errors"][0],
        )

        data["sender"] = safe_delegate.address
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Sender={safe_delegate.address} is not an owner or delegate",
            response.data["non_field_errors"][0],
        )

        # Add delegates (to check there's no issue with delegating twice to the same account)
        safe_contract_delegate = SafeContractDelegateFactory(
            safe_contract__address=safe_address,
            delegate=safe_delegate.address,
            delegator=safe_owners[0].address,
        )
        SafeContractDelegateFactory(
            safe_contract=safe_contract_delegate.safe_contract,
            delegate=safe_delegate.address,
            delegator=safe_owners[1].address,
        )
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        multisig_transaction = MultisigTransaction.objects.first()
        self.assertTrue(multisig_transaction.trusted)
        # Proposer should be the owner address not the delegate
        self.assertNotEqual(multisig_transaction.proposer, safe_delegate.address)
        self.assertEqual(multisig_transaction.proposer, safe_owners[0].address)
        self.assertEqual(
            multisig_transaction.proposed_by_delegate, safe_delegate.address
        )

        data["signature"] = data["signature"] + data["signature"][2:]
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            "Just one signature is expected if using delegates",
            response.data["non_field_errors"][0],
        )

    def test_post_multisig_transactions_with_banned_signatures(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe.address

        data = {
            "to": Account.create().address,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owners[0].address,
            "origin": "Testing origin field",
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(
            b"".join(
                [
                    safe_owner.unsafe_sign_hash(safe_tx_hash)["signature"]
                    for safe_owner in safe_owners
                ]
            )
        )
        with self.settings(BANNED_EOAS={safe_owners[0].address}):
            response = self.client.post(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
            self.assertEqual(
                response.json(),
                {
                    "nonFieldErrors": [
                        f"Signer={safe_owners[0].address} is not authorized to interact with the service"
                    ]
                },
            )

    def test_post_multisig_transaction_with_delegate_call(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address
        try:
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 0)

            data = {
                "to": Account.create().address,
                "value": 0,
                "data": "0x12121212",
                "operation": SafeOperationEnum.DELEGATE_CALL.value,
                "nonce": 0,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": "0x0000000000000000000000000000000000000000",
                "refundReceiver": "0x0000000000000000000000000000000000000000",
                "sender": safe_owner_1.address,
            }
            safe_tx = safe.build_multisig_tx(
                data["to"],
                data["value"],
                data["data"],
                data["operation"],
                data["safeTxGas"],
                data["baseGas"],
                data["gasPrice"],
                data["gasToken"],
                data["refundReceiver"],
                safe_nonce=data["nonce"],
            )
            data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)

            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            # Disable creation with delegate call and not trusted contract
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=True
            ):
                response = self.client.post(
                    reverse("v1:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(
                    response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            # Enable creation with delegate call
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=False
            ):
                response = self.client.post(
                    reverse("v1:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                multisig_transaction_db = MultisigTransaction.objects.first()
                self.assertEqual(multisig_transaction_db.operation, 1)

            # Disable creation with delegate call and trusted contract
            ContractFactory(address=data["to"], trusted_for_delegate_call=True)
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=True
            ):
                response = self.client.post(
                    reverse("v1:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        finally:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()

    def test_safe_balances_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIsNone(response.data[0]["token_address"])
        self.assertEqual(response.data[0]["balance"], str(value))

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        self.assertEqual(Token.objects.count(), 0)
        ERC20TransferFactory(address=erc20.address, to=safe_address)
        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.count(), 1)
        self.assertCountEqual(
            response.json(),
            [
                {"tokenAddress": None, "balance": str(value), "token": None},
                {
                    "tokenAddress": erc20.address,
                    "balance": str(tokens_value),
                    "token": {
                        "name": erc20.functions.name().call(),
                        "symbol": erc20.functions.symbol().call(),
                        "decimals": erc20.functions.decimals().call(),
                        "logoUri": Token.objects.first().get_full_logo_uri(),
                    },
                },
            ],
        )

        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)) + "?trusted=True",
            format="json",
        )
        self.assertCountEqual(
            response.json(),
            [{"tokenAddress": None, "balance": str(value), "token": None}],
        )
        Token.objects.all().update(trusted=True)

        response = self.client.get(
            reverse("v1:history:safe-balances", args=(safe_address,)) + "?trusted=True",
            format="json",
        )
        self.assertCountEqual(
            response.json(),
            [
                {"tokenAddress": None, "balance": str(value), "token": None},
                {
                    "tokenAddress": erc20.address,
                    "balance": str(tokens_value),
                    "token": {
                        "name": erc20.functions.name().call(),
                        "symbol": erc20.functions.symbol().call(),
                        "decimals": erc20.functions.decimals().call(),
                        "logoUri": Token.objects.first().get_full_logo_uri(),
                    },
                },
            ],
        )

    def test_delegates_post(self):
        url = reverse("v1:history:delegates")
        safe_address = Account.create().address
        delegate = Account.create()
        delegator = Account.create()
        label = "Saul Goodman"
        data = {
            "delegate": delegate.address,
            "delegator": delegator.address,
            "label": label,
            "signature": "0x" + "1" * 130,
        }
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            "Signature does not match provided delegator",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data["safe"] = safe_address
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Safe={safe_address} does not exist", response.data["non_field_errors"][0]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        SafeContractFactory(address=safe_address)
        with mock.patch(
            "safe_transaction_service.history.serializers.get_safe_owners",
            return_value=[Account.create().address],
        ) as get_safe_owners_mock:
            response = self.client.post(url, format="json", data=data)
            self.assertIn(
                f"Provided delegator={delegator.address} is not an owner of Safe={safe_address}",
                response.data["non_field_errors"][0],
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            get_safe_owners_mock.return_value = [delegator.address]
            response = self.client.post(url, format="json", data=data)
            self.assertIn(
                f"Signature does not match provided delegator={delegator.address}",
                response.data["non_field_errors"][0],
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # Create delegate
            self.assertEqual(SafeContractDelegate.objects.count(), 0)
            hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate.address)
            data["signature"] = to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            )
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.delegate, delegate.address)
            self.assertEqual(safe_contract_delegate.delegator, delegator.address)
            self.assertEqual(safe_contract_delegate.label, label)
            self.assertEqual(safe_contract_delegate.safe_contract_id, safe_address)
            self.assertEqual(safe_contract_delegate.expiry_date, None)

            # Update label
            label = "Jimmy McGill"
            data["label"] = label
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(SafeContractDelegate.objects.count(), 1)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.label, label)
            self.assertEqual(safe_contract_delegate.expiry_date, None)

        # Create delegate without a Safe
        another_label = "Kim Wexler"
        data = {
            "label": another_label,
            "delegate": delegate.address,
            "delegator": delegator.address,
            "signature": to_0x_hex_str(
                delegator.unsafe_sign_hash(
                    DelegateSignatureHelper.calculate_hash(
                        delegate.address, eth_sign=True
                    )
                )["signature"]
            ),
        }
        response = self.client.post(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)

        # Test not internal server error on contract signature
        signature = signature_to_bytes(0, int(delegator.address, 16), 65) + HexBytes(
            "0" * 65
        )
        data["signature"] = to_0x_hex_str(signature)
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Signature of type=CONTRACT_SIGNATURE for delegator={delegator.address} is not valid",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        queryset = SafeContractDelegate.objects.get_for_safe(
            safe_address, [delegator.address]
        )
        self.assertEqual(len(queryset), 2)
        self.assertCountEqual(
            set(safe_contract_delegate.delegate for safe_contract_delegate in queryset),
            {delegate.address},
        )

    def test_delegates_get(self):
        url = reverse("v1:history:delegates")
        response = self.client.get(url, format="json")
        self.assertEqual(response.data[0], "At least one query param must be provided")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        delegator = Account.create().address

        # Add 2 delegates for the same Safe and delegator and another for a different Safe
        safe_contract_delegate_1 = SafeContractDelegateFactory(delegator=delegator)
        safe_contract = safe_contract_delegate_1.safe_contract
        safe_contract_delegate_2 = SafeContractDelegateFactory(
            safe_contract=safe_contract, delegator=delegator
        )
        safe_contract_delegate_3 = SafeContractDelegateFactory(
            delegate=safe_contract_delegate_1.delegate
        )

        expected = [
            {
                "delegate": safe_contract_delegate_1.delegate,
                "delegator": safe_contract_delegate_1.delegator,
                "label": safe_contract_delegate_1.label,
                "safe": safe_contract.address,
                "expiry_date": datetime_to_str(safe_contract_delegate_1.expiry_date),
            },
            {
                "delegate": safe_contract_delegate_2.delegate,
                "delegator": safe_contract_delegate_2.delegator,
                "label": safe_contract_delegate_2.label,
                "safe": safe_contract.address,
                "expiry_date": datetime_to_str(safe_contract_delegate_2.expiry_date),
            },
        ]
        response = self.client.get(
            url + f"?safe={safe_contract.address}", format="json"
        )
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(url + f"?delegator={delegator}", format="json")
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected = [
            {
                "delegate": safe_contract_delegate_1.delegate,
                "delegator": safe_contract_delegate_1.delegator,
                "label": safe_contract_delegate_1.label,
                "safe": safe_contract.address,
                "expiry_date": datetime_to_str(safe_contract_delegate_1.expiry_date),
            },
            {
                "delegate": safe_contract_delegate_3.delegate,
                "delegator": safe_contract_delegate_3.delegator,
                "label": safe_contract_delegate_3.label,
                "safe": safe_contract_delegate_3.safe_contract_id,
                "expiry_date": datetime_to_str(safe_contract_delegate_3.expiry_date),
            },
        ]
        response = self.client.get(
            url + f"?delegate={safe_contract_delegate_1.delegate}", format="json"
        )
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delegate_delete(self):
        url_name = "v1:history:delegate"
        delegate = Account.create()
        delegator = Account.create()
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate.address)
        # Test delete using delegate signature and then delegator signature
        for signer in (delegate, delegator):
            with self.subTest(signer=signer):
                SafeContractDelegateFactory(
                    delegate=delegate.address, delegator=delegator.address
                )  # Expected to be deleted
                SafeContractDelegateFactory(
                    safe_contract=None,
                    delegate=delegate.address,
                    delegator=delegator.address,
                )  # Expected to be deleted
                SafeContractDelegateFactory(
                    delegate=delegate.address,  # random delegator, should not be deleted
                )
                data = {
                    "signature": to_0x_hex_str(
                        signer.unsafe_sign_hash(hash_to_sign)["signature"]
                    ),
                    "delegator": delegator.address,
                }
                self.assertEqual(SafeContractDelegate.objects.count(), 3)
                response = self.client.delete(
                    reverse(url_name, args=(delegate.address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
                self.assertEqual(SafeContractDelegate.objects.count(), 1)
                response = self.client.delete(
                    reverse(url_name, args=(delegate.address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
                SafeContractDelegate.objects.all().delete()

        # Try an invalid signer
        SafeContractDelegateFactory(
            delegate=delegate.address, delegator=delegator.address
        )
        signer = Account.create()
        data = {
            "signature": to_0x_hex_str(
                signer.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
            "delegator": delegator.address,
        }
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        response = self.client.delete(
            reverse(url_name, args=(delegate.address,)), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Signature does not match provided delegate",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(SafeContractDelegate.objects.count(), 1)

    def test_delete_safe_delegate(self):
        safe_address = Account.create().address
        delegate_address = Account.create().address
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST
        )  # Data is missing

        data = {
            "delegate": Account.create().address,
            "signature": "0x" + "1" * 130,
        }
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(
            {
                "code": 2,
                "message": "Delegate address in body should match the one in the url",
                "arguments": [data["delegate"], delegate_address],
            },
            response.data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        del data["delegate"]
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Safe={safe_address} does not exist", response.data["non_field_errors"][0]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        owner_account = Account.create()
        safe_address = self.deploy_test_safe(owners=[owner_account.address]).address
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Safe={safe_address} does not exist", response.data["non_field_errors"][0]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertIn(
            "Signing owner is not an owner of the Safe",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test eth_sign first
        hash_to_sign = DelegateSignatureHelper.calculate_hash(
            delegate_address, eth_sign=True
        )
        data["signature"] = to_0x_hex_str(
            owner_account.unsafe_sign_hash(hash_to_sign)["signature"]
        )
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            "No SafeContractDelegate matches the given query.", response.data["detail"]
        )

        # Test previous otp
        hash_to_sign = DelegateSignatureHelper.calculate_hash(
            delegate_address, previous_totp=True
        )
        data["signature"] = to_0x_hex_str(
            owner_account.unsafe_sign_hash(hash_to_sign)["signature"]
        )
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            "No SafeContractDelegate matches the given query.", response.data["detail"]
        )

        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address)
        data["signature"] = to_0x_hex_str(
            owner_account.unsafe_sign_hash(hash_to_sign)["signature"]
        )
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            "No SafeContractDelegate matches the given query.", response.data["detail"]
        )

        SafeContractDelegateFactory(
            safe_contract=safe_contract, delegate=delegate_address
        )
        SafeContractDelegateFactory(
            safe_contract=safe_contract, delegate=Account.create().address
        )
        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)

        # Check if a delegate can delete itself
        SafeContractDelegate.objects.all().delete()
        delegate_account = Account().create()
        SafeContractDelegateFactory(
            safe_contract=safe_contract, delegate=delegate_account.address
        )
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_account.address)
        data["signature"] = to_0x_hex_str(
            delegate_account.unsafe_sign_hash(hash_to_sign)["signature"]
        )
        response = self.client.delete(
            reverse(
                "v1:history:safe-delegate",
                args=(safe_address, delegate_account.address),
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SafeContractDelegate.objects.count(), 0)

    def test_incoming_transfers_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:incoming-transfers", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(len(response.data["results"]), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        ethereum_tx_hash = (
            "0x5a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        ethereum_tx = EthereumTxFactory(tx_hash=ethereum_tx_hash)
        internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx, trace_address="0,1", to=safe_address, value=value
        )
        internal_tx_transfer_id = (
            "i5a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d590,1"
        )
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(
            reverse("v1:history:incoming-transfers", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["value"], str(value))
        # Check Etag header
        self.assertTrue(response["Etag"])

        # Test filters
        block_number = internal_tx.ethereum_tx.block_id
        url = (
            reverse("v1:history:incoming-transfers", args=(safe_address,))
            + f"?block_number__gt={block_number}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        # Add from tx. Result should be the same
        InternalTxFactory(_from=safe_address, value=value)
        response = self.client.get(
            reverse("v1:history:incoming-transfers", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["value"], str(value))

        url = (
            reverse("v1:history:incoming-transfers", args=(safe_address,))
            + f"?block_number__gt={block_number - 1}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        token_value = 6
        erc20_tx_hash = (
            "0x7a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc20_tx = EthereumTxFactory(tx_hash=erc20_tx_hash)
        ethereum_erc_20_event = ERC20TransferFactory(
            ethereum_tx=erc20_tx, to=safe_address, value=token_value, log_index=12
        )
        erc20_transfer_id = (
            "e7a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d5912"
        )
        token = TokenFactory(address=ethereum_erc_20_event.address)
        response = self.client.get(
            reverse("v1:history:incoming-transfers", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "type": TransferType.ERC20_TRANSFER.name,
                    "executionDate": datetime_to_str(
                        ethereum_erc_20_event.ethereum_tx.block.timestamp
                    ),
                    "transferId": erc20_transfer_id,
                    "transactionHash": ethereum_erc_20_event.ethereum_tx_id,
                    "blockNumber": ethereum_erc_20_event.ethereum_tx.block_id,
                    "to": safe_address,
                    "value": str(token_value),
                    "tokenId": None,
                    "tokenAddress": ethereum_erc_20_event.address,
                    "from": ethereum_erc_20_event._from,
                    "tokenInfo": {
                        "type": "ERC20",
                        "address": token.address,
                        "name": token.name,
                        "symbol": token.symbol,
                        "decimals": token.decimals,
                        "logoUri": token.get_full_logo_uri(),
                        "trusted": token.trusted,
                    },
                },
                {
                    "type": TransferType.ETHER_TRANSFER.name,
                    "executionDate": datetime_to_str(
                        internal_tx.ethereum_tx.block.timestamp
                    ),
                    "transferId": internal_tx_transfer_id,
                    "transactionHash": internal_tx.ethereum_tx_id,
                    "blockNumber": internal_tx.ethereum_tx.block_id,
                    "to": safe_address,
                    "value": str(value),
                    "tokenId": None,
                    "tokenAddress": None,
                    "from": internal_tx._from,
                    "tokenInfo": None,
                },
            ],
        )

        token_id = 17
        erc721_tx_hash = (
            "0x6a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc721_tx = EthereumTxFactory(tx_hash=erc721_tx_hash)
        ethereum_erc_721_event = ERC721TransferFactory(
            ethereum_tx=erc721_tx, to=safe_address, token_id=token_id, log_index=123
        )
        erc721_transfer_id = (
            "e6a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59123"
        )
        response = self.client.get(
            reverse("v1:history:incoming-transfers", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "type": TransferType.ERC721_TRANSFER.name,
                    "executionDate": datetime_to_str(
                        ethereum_erc_721_event.ethereum_tx.block.timestamp
                    ),
                    "transferId": erc721_transfer_id,
                    "transactionHash": ethereum_erc_721_event.ethereum_tx_id,
                    "blockNumber": ethereum_erc_721_event.ethereum_tx.block_id,
                    "to": safe_address,
                    "value": None,
                    "tokenId": str(token_id),
                    "tokenAddress": ethereum_erc_721_event.address,
                    "from": ethereum_erc_721_event._from,
                    "tokenInfo": None,
                },
                {
                    "type": TransferType.ERC20_TRANSFER.name,
                    "executionDate": datetime_to_str(
                        ethereum_erc_20_event.ethereum_tx.block.timestamp
                    ),
                    "transferId": erc20_transfer_id,
                    "transactionHash": ethereum_erc_20_event.ethereum_tx_id,
                    "blockNumber": ethereum_erc_20_event.ethereum_tx.block_id,
                    "to": safe_address,
                    "value": str(token_value),
                    "tokenId": None,
                    "tokenAddress": ethereum_erc_20_event.address,
                    "from": ethereum_erc_20_event._from,
                    "tokenInfo": {
                        "type": "ERC20",
                        "address": token.address,
                        "name": token.name,
                        "symbol": token.symbol,
                        "decimals": token.decimals,
                        "logoUri": token.get_full_logo_uri(),
                        "trusted": token.trusted,
                    },
                },
                {
                    "type": TransferType.ETHER_TRANSFER.name,
                    "executionDate": datetime_to_str(
                        internal_tx.ethereum_tx.block.timestamp
                    ),
                    "transferId": internal_tx_transfer_id,
                    "transactionHash": internal_tx.ethereum_tx_id,
                    "blockNumber": internal_tx.ethereum_tx.block_id,
                    "to": safe_address,
                    "value": str(value),
                    "tokenId": None,
                    "tokenAddress": None,
                    "from": internal_tx._from,
                    "tokenInfo": None,
                },
            ],
        )

    def test_transfers_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(len(response.data["results"]), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        ethereum_tx_hash = (
            "0x5a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        ethereum_tx = EthereumTxFactory(tx_hash=ethereum_tx_hash)
        internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx, trace_address="0,1,1", to=safe_address, value=value
        )
        internal_tx_transfer_id = (
            "i5a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d590,1,1"
        )
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["value"], str(value))
        # Check Etag header
        self.assertTrue(response["Etag"])

        # Test filters
        block_number = internal_tx.ethereum_tx.block_id
        url = (
            reverse("v1:history:transfers", args=(safe_address,))
            + f"?block_number__gt={block_number}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        url = (
            reverse("v1:history:transfers", args=(safe_address,))
            + f"?block_number__gt={block_number - 1}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        url = (
            reverse("v1:history:transfers", args=(safe_address,))
            + f"?transaction_hash={internal_tx.ethereum_tx_id}"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        url = (
            reverse("v1:history:transfers", args=(safe_address,))
            + "?transaction_hash=0x2345"
        )
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Add from tx
        ethereum_tx_hash_2 = (
            "0x5f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        ethereum_tx_2 = EthereumTxFactory(tx_hash=ethereum_tx_hash_2)
        internal_tx_2 = InternalTxFactory(
            ethereum_tx=ethereum_tx_2, _from=safe_address, value=value, trace_address=""
        )
        internal_tx_2_transfer_id = (
            "i5f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["value"], str(value))
        self.assertEqual(response.data["results"][1]["value"], str(value))

        token_value = 6
        erc20_tx_hash = (
            "0x7a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc20_tx = EthereumTxFactory(tx_hash=erc20_tx_hash)
        ethereum_erc_20_event = ERC20TransferFactory(
            ethereum_tx=erc20_tx, to=safe_address, value=token_value, log_index=12
        )
        erc20_transfer_id = (
            "e7a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d5912"
        )
        erc20_tx_hash_2 = (
            "0x8a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc20_tx_2 = EthereumTxFactory(tx_hash=erc20_tx_hash_2)
        ethereum_erc_20_event_2 = ERC20TransferFactory(
            ethereum_tx=erc20_tx_2,
            _from=safe_address,
            value=token_value,
            log_index=1299,
        )
        erc20_transfer_id_2 = (
            "e8a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d591299"
        )
        token = TokenFactory(address=ethereum_erc_20_event.address)
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)
        expected_results = [
            {
                "type": TransferType.ERC20_TRANSFER.name,
                "executionDate": datetime_to_str(
                    ethereum_erc_20_event_2.ethereum_tx.block.timestamp
                ),
                "blockNumber": ethereum_erc_20_event_2.ethereum_tx.block_id,
                "transferId": erc20_transfer_id_2,
                "transactionHash": ethereum_erc_20_event_2.ethereum_tx_id,
                "to": ethereum_erc_20_event_2.to,
                "value": str(token_value),
                "tokenId": None,
                "tokenAddress": ethereum_erc_20_event_2.address,
                "from": safe_address,
                "tokenInfo": None,
            },
            {
                "type": TransferType.ERC20_TRANSFER.name,
                "executionDate": datetime_to_str(
                    ethereum_erc_20_event.ethereum_tx.block.timestamp
                ),
                "blockNumber": ethereum_erc_20_event.ethereum_tx.block_id,
                "transferId": erc20_transfer_id,
                "transactionHash": ethereum_erc_20_event.ethereum_tx_id,
                "to": safe_address,
                "value": str(token_value),
                "tokenId": None,
                "tokenAddress": ethereum_erc_20_event.address,
                "from": ethereum_erc_20_event._from,
                "tokenInfo": {
                    "type": "ERC20",
                    "address": token.address,
                    "name": token.name,
                    "symbol": token.symbol,
                    "decimals": token.decimals,
                    "logoUri": token.get_full_logo_uri(),
                    "trusted": token.trusted,
                },
            },
            {
                "type": TransferType.ETHER_TRANSFER.name,
                "executionDate": datetime_to_str(
                    internal_tx_2.ethereum_tx.block.timestamp
                ),
                "blockNumber": internal_tx_2.ethereum_tx.block_id,
                "transferId": internal_tx_2_transfer_id,
                "transactionHash": internal_tx_2.ethereum_tx_id,
                "to": internal_tx_2.to,
                "value": str(value),
                "tokenId": None,
                "tokenAddress": None,
                "from": safe_address,
                "tokenInfo": None,
            },
            {
                "type": TransferType.ETHER_TRANSFER.name,
                "executionDate": datetime_to_str(
                    internal_tx.ethereum_tx.block.timestamp
                ),
                "blockNumber": internal_tx.ethereum_tx.block_id,
                "transferId": internal_tx_transfer_id,
                "transactionHash": internal_tx.ethereum_tx_id,
                "to": safe_address,
                "value": str(value),
                "tokenId": None,
                "tokenAddress": None,
                "from": internal_tx._from,
                "tokenInfo": None,
            },
        ]
        self.assertEqual(response.json()["results"], expected_results)

        token_id = 17
        erc721_tx_hash = (
            "0x1f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc721_tx = EthereumTxFactory(tx_hash=erc721_tx_hash)
        ethereum_erc_721_event = ERC721TransferFactory(
            ethereum_tx=erc721_tx, to=safe_address, token_id=token_id, log_index=0
        )
        erc721_transfer_id = (
            "e1f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d590"
        )
        erc721_tx_hash_2 = (
            "0x2f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc721_tx_2 = EthereumTxFactory(tx_hash=erc721_tx_hash_2)
        ethereum_erc_721_event_2 = ERC721TransferFactory(
            ethereum_tx=erc721_tx_2, _from=safe_address, token_id=token_id, log_index=2
        )
        erc721_transfer_id_2 = (
            "e2f6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d592"
        )
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        expected_results = [
            {
                "type": TransferType.ERC721_TRANSFER.name,
                "executionDate": datetime_to_str(
                    ethereum_erc_721_event_2.ethereum_tx.block.timestamp
                ),
                "transactionHash": ethereum_erc_721_event_2.ethereum_tx_id,
                "transferId": erc721_transfer_id_2,
                "blockNumber": ethereum_erc_721_event_2.ethereum_tx.block_id,
                "to": ethereum_erc_721_event_2.to,
                "value": None,
                "tokenId": str(token_id),
                "tokenAddress": ethereum_erc_721_event_2.address,
                "from": safe_address,
                "tokenInfo": None,
            },
            {
                "type": TransferType.ERC721_TRANSFER.name,
                "executionDate": datetime_to_str(
                    ethereum_erc_721_event.ethereum_tx.block.timestamp
                ),
                "transactionHash": ethereum_erc_721_event.ethereum_tx_id,
                "transferId": erc721_transfer_id,
                "blockNumber": ethereum_erc_721_event.ethereum_tx.block_id,
                "to": safe_address,
                "value": None,
                "tokenId": str(token_id),
                "tokenAddress": ethereum_erc_721_event.address,
                "from": ethereum_erc_721_event._from,
                "tokenInfo": None,
            },
        ] + expected_results
        self.assertEqual(response.json()["results"], expected_results)

        # Test ether, erc20 and erc721 filters
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?erc20=true",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertEqual(result["type"], TransferType.ERC20_TRANSFER.name)

        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?erc20=false",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertNotEqual(result["type"], TransferType.ERC20_TRANSFER.name)

        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?erc721=true",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertEqual(result["type"], TransferType.ERC721_TRANSFER.name)

        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?erc721=false",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertNotEqual(result["type"], TransferType.ERC721_TRANSFER.name)

        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?ether=true",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertEqual(result["type"], TransferType.ETHER_TRANSFER.name)

        url = reverse("v1:history:transfers", args=(safe_address,)) + "?ether=false"
        response = self.client.get(url, format="json")
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertNotEqual(result["type"], TransferType.ETHER_TRANSFER.name)

        # Test that the result should be cached
        # Mock get_queryset with empty queryset return value to get proper error in case of fail
        with mock.patch.object(
            SafeTransferListView,
            "get_queryset",
            return_value=InternalTx.objects.none(),
        ) as patched_queryset:
            response = self.client.get(url, format="json")
            # queryset shouldn't be called
            patched_queryset.assert_not_called()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertGreater(len(response.data["results"]), 0)
            for result in response.data["results"]:
                self.assertNotEqual(result["type"], TransferType.ETHER_TRANSFER.name)

    def test_get_transfer_view(self):
        # test wrong random transfer_id
        transfer_id = FuzzyText(length=6).fuzz()
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # test invalid erc20 transfer_id empty log_index
        transfer_id = (
            "e27e15ba8dea473d98c80a6b45d372c0f3c6f8c184177044c935c37eb419d7216"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # test invalid erc20 transfer id wrong log index
        transfer_id = (
            "e27e15ba8dea473d98c80a6b45d372c0f3c6f8c184177044c935c37eb419d72161,1"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_address = Account.create().address
        ethereum_tx_hash = (
            "0x4f6754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        ethereum_tx = EthereumTxFactory(tx_hash=ethereum_tx_hash)
        internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx, to=safe_address, trace_address="0"
        )
        # Test 404
        wrong_transfer_id = (
            "e3a6854140f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d592"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(wrong_transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test getting ether incomming transfer
        transfer_id = (
            "i4f6754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d590"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_result = {
            "type": TransferType.ETHER_TRANSFER.name,
            "executionDate": datetime_to_str(internal_tx.ethereum_tx.block.timestamp),
            "blockNumber": internal_tx.ethereum_tx.block_id,
            "transferId": transfer_id,
            "transactionHash": internal_tx.ethereum_tx_id,
            "to": safe_address,
            "value": str(internal_tx.value),
            "tokenId": None,
            "tokenAddress": None,
            "from": internal_tx._from,
            "tokenInfo": None,
        }
        self.assertEqual(response.json(), expected_result)

        # test internal_tx transfer_id empty trace_address
        ethereum_tx_hash = (
            "0x12bafc5ee165d825201a24418e00bef6039bb06f6d09420ab1c5f7b4098c0809"
        )
        ethereum_tx = EthereumTxFactory(tx_hash=ethereum_tx_hash)
        internal_tx_empty_trace_address = InternalTxFactory(
            ethereum_tx=ethereum_tx, to=safe_address, trace_address=""
        )
        transfer_id_empty_trace_address = (
            "i12bafc5ee165d825201a24418e00bef6039bb06f6d09420ab1c5f7b4098c0809"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id_empty_trace_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_result = {
            "type": TransferType.ETHER_TRANSFER.name,
            "executionDate": datetime_to_str(
                internal_tx_empty_trace_address.ethereum_tx.block.timestamp
            ),
            "blockNumber": internal_tx_empty_trace_address.ethereum_tx.block_id,
            "transferId": transfer_id_empty_trace_address,
            "transactionHash": internal_tx_empty_trace_address.ethereum_tx_id,
            "to": safe_address,
            "value": str(internal_tx_empty_trace_address.value),
            "tokenId": None,
            "tokenAddress": None,
            "from": internal_tx_empty_trace_address._from,
            "tokenInfo": None,
        }
        self.assertEqual(response.json(), expected_result)

        # Test filtering ERC20 transfer by transfer_id
        erc20_tx_hash = (
            "0x406754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc20_tx = EthereumTxFactory(tx_hash=erc20_tx_hash)
        ethereum_erc_20_event = ERC20TransferFactory(
            ethereum_tx=erc20_tx, to=safe_address, log_index=20
        )
        token = TokenFactory(address=ethereum_erc_20_event.address)
        transfer_id = (
            "e406754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d5920"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_result = {
            "type": TransferType.ERC20_TRANSFER.name,
            "executionDate": datetime_to_str(
                ethereum_erc_20_event.ethereum_tx.block.timestamp
            ),
            "blockNumber": ethereum_erc_20_event.ethereum_tx.block_id,
            "transferId": transfer_id,
            "transactionHash": ethereum_erc_20_event.ethereum_tx_id,
            "to": safe_address,
            "value": str(ethereum_erc_20_event.value),
            "tokenId": None,
            "tokenAddress": ethereum_erc_20_event.address,
            "from": ethereum_erc_20_event._from,
            "tokenInfo": {
                "type": "ERC20",
                "address": token.address,
                "name": token.name,
                "symbol": token.symbol,
                "decimals": token.decimals,
                "logoUri": token.get_full_logo_uri(),
                "trusted": token.trusted,
            },
        }
        self.assertEqual(response.json(), expected_result)

        # Test filtering ERC721 transfer by transfer_id
        token_id = 17
        erc721_tx_hash = (
            "0x306754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59"
        )
        erc721_tx = EthereumTxFactory(tx_hash=erc721_tx_hash)
        ethereum_erc_721_event = ERC721TransferFactory(
            ethereum_tx=erc721_tx, to=safe_address, token_id=token_id, log_index=721
        )
        transfer_id = (
            "e306754000f0432d3b5e6d8341597ec3c5338239f8d311de9061fbc959f443d59721"
        )
        response = self.client.get(
            reverse("v1:history:transfer", args=(transfer_id,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_result = {
            "type": TransferType.ERC721_TRANSFER.name,
            "executionDate": datetime_to_str(
                ethereum_erc_721_event.ethereum_tx.block.timestamp
            ),
            "transactionHash": ethereum_erc_721_event.ethereum_tx_id,
            "transferId": transfer_id,
            "blockNumber": ethereum_erc_721_event.ethereum_tx.block_id,
            "to": safe_address,
            "value": None,
            "tokenId": str(token_id),
            "tokenAddress": ethereum_erc_721_event.address,
            "from": ethereum_erc_721_event._from,
            "tokenInfo": None,
        }
        self.assertEqual(response.json(), expected_result)

    def test_safe_creation_view(self):
        invalid_address = "0x2A"
        response = self.client.get(
            reverse("v1:history:safe-creation", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-creation", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        with mock.patch.object(
            TracingManager, "trace_transaction", autospec=True, return_value=[]
        ):
            # Insert create contract internal tx
            internal_tx = InternalTxFactory(
                contract_address=safe_address,
                trace_address="0,0",
                ethereum_tx__status=1,
                tx_type=InternalTxType.CREATE.value,
            )
            response = self.client.get(
                reverse("v1:history:safe-creation", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            created_iso = datetime_to_str(internal_tx.ethereum_tx.block.timestamp)
            expected = {
                "created": created_iso,
                "creator": internal_tx.ethereum_tx._from,
                "factory_address": internal_tx._from,
                "master_copy": None,
                "setup_data": None,
                "salt_nonce": None,
                "data_decoded": None,
                "transaction_hash": internal_tx.ethereum_tx_id,
                "user_operation": None,
            }
            self.assertDictEqual(response.data, expected)

        # Next children internal_tx should not alter the result
        another_trace = dict(call_trace)
        another_trace["traceAddress"] = [0, 0, 0]
        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=[another_trace],
        ):
            response = self.client.get(
                reverse("v1:history:safe-creation", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertDictEqual(response.data, expected)

        # Test 4337 SafeOperation showing in the creation
        safe_operation = aa_factories.SafeOperationFactory(
            user_operation__ethereum_tx_id=internal_tx.ethereum_tx_id,
            user_operation__sender=safe_address,
            user_operation__init_code=HexBytes("0x1234"),
        )
        response = self.client.get(
            reverse("v1:history:safe-creation", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected["user_operation"] = {
            "sender": safe_operation.user_operation.sender,
            "nonce": str(safe_operation.user_operation.nonce),
            "user_operation_hash": safe_operation.user_operation.hash,
            "ethereum_tx_hash": internal_tx.ethereum_tx_id,
            "init_code": "0x1234",
            "call_data": "0x",
            "call_gas_limit": str(safe_operation.user_operation.call_gas_limit),
            "verification_gas_limit": str(
                safe_operation.user_operation.verification_gas_limit
            ),
            "pre_verification_gas": str(
                safe_operation.user_operation.pre_verification_gas
            ),
            "max_fee_per_gas": str(safe_operation.user_operation.max_fee_per_gas),
            "max_priority_fee_per_gas": str(
                safe_operation.user_operation.max_priority_fee_per_gas
            ),
            "paymaster": safe_operation.user_operation.paymaster,
            "paymaster_data": "0x",
            "signature": to_0x_hex_str(safe_operation.user_operation.signature),
            "entry_point": safe_operation.user_operation.entry_point,
            "safe_operation": {
                "created": datetime_to_str(safe_operation.created),
                "modified": datetime_to_str(safe_operation.created),
                "safe_operation_hash": safe_operation.hash,
                "valid_after": datetime_to_str(safe_operation.valid_after),
                "valid_until": datetime_to_str(safe_operation.valid_until),
                "module_address": safe_operation.module_address,
                "confirmations": [],
                "prepared_signature": to_0x_hex_str(
                    HexBytes(safe_operation.build_signature())
                ),
            },
        }

        self.assertIsNotNone(response.data["user_operation"])
        self.assertDictEqual(response.data, expected)
        safe_operation.user_operation.delete()

        another_trace_2 = dict(call_trace)
        another_trace_2["traceAddress"] = [0]
        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=[another_trace, another_trace_2],
        ):
            # `another_trace_2` should change the `creator` and `master_copy` and `setup_data` should appear

            for test_data, data_decoded, salt_nonce in [
                (create_test_data_v1_0_0, data_decoded_v1_0_0, None),
                (create_test_data_v1_1_1, data_decoded_v1_1_1, "3087219459602"),
                (
                    create_cpk_test_data,
                    data_decoded_cpk,
                    "94030236624644942756909922368015716412234033278725318725234853277280604175973",
                ),
                (create_v1_4_1_test_data, data_decoded_v1_4_1, "1694202208610"),
            ]:
                with self.subTest(test_data=test_data, data_decoded=data_decoded):
                    another_trace_2["action"]["input"] = HexBytes(test_data["data"])
                    response = self.client.get(
                        reverse("v1:history:safe-creation", args=(safe_address,)),
                        format="json",
                    )
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    created_iso = datetime_to_str(
                        internal_tx.ethereum_tx.block.timestamp
                    )
                    self.assertDictEqual(
                        response.data,
                        {
                            "created": created_iso,
                            "creator": another_trace_2["action"]["from"],
                            "transaction_hash": internal_tx.ethereum_tx_id,
                            "factory_address": internal_tx._from,
                            "master_copy": test_data["master_copy"],
                            "setup_data": test_data["setup_data"],
                            "salt_nonce": salt_nonce,
                            "data_decoded": data_decoded,
                            "user_operation": None,
                        },
                    )

    def test_safe_info_view(self):
        invalid_address = "0x2A"
        response = self.client.get(
            reverse("v1:history:safe-info", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-info", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.get(
            reverse("v1:history:safe-info", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(
            response.data,
            {
                "code": 50,
                "message": "Cannot get Safe info from blockchain",
                "arguments": [safe_address],
            },
        )

        safe_last_status = SafeLastStatusFactory(address=safe_address, nonce=0)
        # For nonce=0, try to get info from blockchain
        response = self.client.get(
            reverse("v1:history:safe-info", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(
            response.data,
            {
                "code": 50,
                "message": "Cannot get Safe info from blockchain",
                "arguments": [safe_address],
            },
        )

        # Test blockchain Safe
        blockchain_safe = self.deploy_test_safe()
        response = self.client.get(
            reverse("v1:history:safe-info", args=(blockchain_safe.address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=blockchain_safe.address)
        SafeMasterCopyFactory(
            address=blockchain_safe.retrieve_master_copy_address(), version="1.25.0"
        )
        response = self.client.get(
            reverse("v1:history:safe-info", args=(blockchain_safe.address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            response.data,
            {
                "address": blockchain_safe.address,
                "nonce": "0",
                "threshold": blockchain_safe.retrieve_threshold(),
                "owners": blockchain_safe.retrieve_owners(),
                "master_copy": blockchain_safe.retrieve_master_copy_address(),
                "modules": [],
                "fallback_handler": blockchain_safe.retrieve_fallback_handler(),
                "guard": NULL_ADDRESS,
                "version": "1.25.0",
            },
        )

        # Uncomment if this method is used again on `SafeInfoView`
        """
        with mock.patch.object(SafeService, "get_safe_info") as get_safe_info_mock:
            safe_info_mock = SafeInfo(
                safe_address,
                Account.create().address,
                Account.create().address,
                Account.create().address,
                [Account.create().address],
                5,
                [Account.create().address, Account.create().address],
                1,
                "1.3.0",
            )
            get_safe_info_mock.return_value = safe_info_mock
            response = self.client.get(
                reverse("v1:history:safe-info", args=(safe_address,)), format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertDictEqual(
                response.data,
                {
                    "address": safe_address,
                    "nonce": safe_info_mock.nonce,
                    "threshold": safe_info_mock.threshold,
                    "owners": safe_info_mock.owners,
                    "master_copy": safe_info_mock.master_copy,
                    "modules": safe_info_mock.modules,
                    "fallback_handler": safe_info_mock.fallback_handler,
                    "guard": safe_info_mock.guard,
                    "version": "1.3.0",
                },
            )

        safe_last_status.nonce = 1
        safe_last_status.save(update_fields=["nonce"])
        response = self.client.get(
            reverse("v1:history:safe-info", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(
            response.data,
            {
                "address": safe_address,
                "nonce": safe_last_status.nonce,
                "threshold": safe_last_status.threshold,
                "owners": safe_last_status.owners,
                "master_copy": safe_last_status.master_copy,
                "modules": safe_last_status.enabled_modules,
                "fallback_handler": safe_last_status.fallback_handler,
                "guard": safe_last_status.guard,
                "version": None,
            },
        )

        SafeMasterCopyFactory(address=safe_last_status.master_copy, version="1.3.0")
        response = self.client.get(
            reverse("v1:history:safe-info", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(
            response.data,
            {
                "address": safe_address,
                "nonce": safe_last_status.nonce,
                "threshold": safe_last_status.threshold,
                "owners": safe_last_status.owners,
                "master_copy": safe_last_status.master_copy,
                "modules": safe_last_status.enabled_modules,
                "fallback_handler": safe_last_status.fallback_handler,
                "guard": NULL_ADDRESS,
                "version": "1.3.0",
            },
        )
        """
        SafeMasterCopy.objects.get_version_for_address.cache_clear()

    def _test_singletons_view(self, url: str):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        deployed_block_number = 2
        last_indexed_block_number = 5
        safe_master_copy = SafeMasterCopyFactory(
            initial_block_number=deployed_block_number,
            tx_block_number=last_indexed_block_number,
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_master_copy = [
            {
                "address": safe_master_copy.address,
                "version": safe_master_copy.version,
                "deployer": safe_master_copy.deployer,
                "deployed_block_number": deployed_block_number,
                "last_indexed_block_number": last_indexed_block_number,
                "l2": False,
            }
        ]
        self.assertCountEqual(response.data, expected_master_copy)

        safe_master_copy = SafeMasterCopyFactory(l2=True)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_l2_master_copy = [
            {
                "address": safe_master_copy.address,
                "version": safe_master_copy.version,
                "deployer": safe_master_copy.deployer,
                "deployed_block_number": 0,
                "last_indexed_block_number": 0,
                "l2": True,
            }
        ]

        self.assertCountEqual(
            response.data, expected_master_copy + expected_l2_master_copy
        )

        with self.settings(ETH_L2_NETWORK=True):
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertCountEqual(response.data, expected_l2_master_copy)

    def test_singletons_view(self):
        url = reverse("v1:history:singletons")
        return self._test_singletons_view(url)

    def test_modules_view(self):
        invalid_address = "0x2A"
        response = self.client.get(
            reverse("v1:history:modules", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        module_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:modules", args=(module_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["safes"], [])

        safe_last_status = SafeLastStatusFactory(enabled_modules=[module_address])
        response = self.client.get(
            reverse("v1:history:modules", args=(module_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["safes"], [safe_last_status.address])

        safe_status_2 = SafeLastStatusFactory(enabled_modules=[module_address])
        SafeStatusFactory()  # Test that other SafeStatus don't appear
        response = self.client.get(
            reverse("v1:history:modules", args=(module_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            response.data["safes"], [safe_last_status.address, safe_status_2.address]
        )

    def test_owners_view(self):
        invalid_address = "0x2A"
        response = self.client.get(
            reverse("v1:history:owners", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(reverse("v1:history:owners", args=(owner_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["safes"], [])

        safe_last_status = SafeLastStatusFactory(owners=[owner_address])
        response = self.client.get(
            reverse("v1:history:owners", args=(owner_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["safes"], [safe_last_status.address])

        safe_status_2 = SafeLastStatusFactory(owners=[owner_address])
        SafeStatusFactory()  # Test that other SafeStatus don't appear
        response = self.client.get(
            reverse("v1:history:owners", args=(owner_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            response.data["safes"], [safe_last_status.address, safe_status_2.address]
        )

    def test_data_decoder_view(self):
        response = self.client.post(
            reverse("v1:history:data-decoder"), format="json", data={"data": "0x12"}
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        response = self.client.post(
            reverse("v1:history:data-decoder"),
            format="json",
            data={"data": "0x12121212"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        add_owner_with_threshold_data = HexBytes(
            "0x0d582f130000000000000000000000001b9a0da11a5cace4e7035993cbb2e4"
            "b1b3b164cf000000000000000000000000000000000000000000000000000000"
            "0000000001"
        )
        response = self.client.post(
            reverse("v1:history:data-decoder"),
            format="json",
            data={"data": to_0x_hex_str(add_owner_with_threshold_data)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch.object(Safe, "estimate_tx_gas", return_value=52000, autospec=True)
    def test_estimate_multisig_tx_view(self, estimate_tx_gas_mock: MagicMock):
        safe_address = Account.create().address
        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
        }
        response = self.client.post(
            reverse("v1:history:multisig-transaction-estimate", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.post(
            reverse("v1:history:multisig-transaction-estimate", args=(safe_address,)),
            format="json",
            data={},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            reverse("v1:history:multisig-transaction-estimate", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"safe_tx_gas": str(estimate_tx_gas_mock.return_value)}
        )
        with mock.patch(
            "safe_transaction_service.history.views.settings.ETH_L2_NETWORK",
            return_value=True,
        ):
            response = self.client.post(
                reverse(
                    "v1:history:multisig-transaction-estimate", args=(safe_address,)
                ),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {"safe_tx_gas": "0"})

        estimate_tx_gas_mock.side_effect = CannotEstimateGas
        response = self.client.post(
            reverse("v1:history:multisig-transaction-estimate", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        estimate_tx_gas_mock.side_effect = ReadTimeout
        response = self.client.post(
            reverse("v1:history:multisig-transaction-estimate", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_safe_export_view(self):
        """Test the export endpoint for CSV export functionality"""
        safe_address = Account.create().address
        # Test with non-existent safe
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Create safe contract
        SafeContractFactory(address=safe_address)

        # Test with no transactions
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

        # Create some test data
        ethereum_tx = EthereumTxFactory()
        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx=ethereum_tx, trusted=True
        )

        # Create ERC20 transfer
        token = TokenFactory(
            address=Account.create().address, symbol="TEST", decimals=18
        )
        erc20_transfer = ERC20TransferFactory(
            ethereum_tx=ethereum_tx,
            address=token.address,
            _from=Account.create().address,
            to=safe_address,
            value=1000000000000000000,  # 1 token with 18 decimals
        )

        # Test basic export
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.json()["results"][0]
        self.assertEqual(result["safe"], safe_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], "1000000000000000000")
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test pagination
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,))
            + "?limit=1&offset=0",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["next"])  # No more pages
        self.assertIsNone(response.data["previous"])

        # Test date filtering
        future_date = timezone.now() + datetime.timedelta(days=1)
        params = urlencode({"execution_date__gte": future_date.isoformat()})
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)) + f"?{params}",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        past_date = timezone.now() - datetime.timedelta(days=1)
        params = urlencode({"execution_date__lte": past_date.isoformat()})
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)) + f"?{params}",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        # Test invalid date format
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,))
            + "?execution_date__gte=invalid-date",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test limit validation
        response = self.client.get(
            reverse("v1:history:safe-export", args=(safe_address,)) + "?limit=2000",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should default to 1000
        self.assertEqual(len(response.data["results"]), 1)

    def _setup_export_tests(self):
        self.token = TokenFactory(
            address=Account.create().address, symbol="TEST", decimals=18
        )
        self.nft_token = TokenFactory(
            address=Account.create().address, symbol="NFT", decimals=None
        )
        self.safe_address = Account.create().address
        self.external_address = Account.create().address
        SafeContractFactory(address=self.safe_address)

    def test_export_view_erc20_transfers(self):
        self._setup_export_tests()
        # Test OUTGOING ERC20 from multisig transaction
        ethereum_tx_multisig_out = EthereumTxFactory()
        multisig_tx_out = MultisigTransactionFactory(
            safe=self.safe_address, ethereum_tx=ethereum_tx_multisig_out, trusted=True
        )
        multisig_outgoing_erc20_transfer = ERC20TransferFactory(
            ethereum_tx=ethereum_tx_multisig_out,
            address=self.token.address,
            _from=self.safe_address,
            to=self.external_address,
            value=1000000000000000000,  # 1 token with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(multisig_outgoing_erc20_transfer.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test INCOMING ERC20 from multisig transaction
        ethereum_tx_multisig_in = EthereumTxFactory()
        multisig_tx_in = MultisigTransactionFactory(
            safe=self.safe_address, ethereum_tx=ethereum_tx_multisig_in, trusted=True
        )
        multisig_incoming_erc20_transfer = ERC20TransferFactory(
            ethereum_tx=ethereum_tx_multisig_in,
            address=self.token.address,
            _from=self.external_address,
            to=self.safe_address,
            value=2000000000000000000,  # 2 tokens with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)

        # Check the incoming transaction (should be first in results due to ordering)
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(multisig_incoming_erc20_transfer.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test OUTGOING ERC20 from module transaction
        ethereum_tx_module_out = EthereumTxFactory()
        module_contract_address = Account.create().address
        module_internal_tx_out = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_out, _from=self.safe_address, value=0
        )
        module_transaction_out = ModuleTransactionFactory(
            internal_tx=module_internal_tx_out,
            safe=self.safe_address,
            to=module_contract_address,
        )
        module_outgoing_erc20 = ERC20TransferFactory(
            ethereum_tx=ethereum_tx_module_out,
            address=self.token.address,
            _from=self.safe_address,
            to=self.external_address,
            value=3000000000000000000,  # 3 tokens with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 3)

        # Check the module outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(module_outgoing_erc20.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test INCOMING ERC20 from module transaction
        ethereum_tx_module_in = EthereumTxFactory()
        module_internal_tx_in = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_in, _from=self.safe_address, value=0
        )
        module_transaction_in = ModuleTransactionFactory(
            internal_tx=module_internal_tx_in,
            safe=self.safe_address,
            to=module_contract_address,
        )
        module_incoming_erc20 = ERC20TransferFactory(
            ethereum_tx=ethereum_tx_module_in,
            address=self.token.address,
            _from=self.external_address,
            to=self.safe_address,
            value=4000000000000000000,  # 4 tokens with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)
        self.assertEqual(len(response.data["results"]), 4)

        # Check the module incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(module_incoming_erc20.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test INCOMING ERC20 from standalone transaction
        standalone_incoming_erc20 = ERC20TransferFactory(
            address=self.token.address,
            _from=self.external_address,
            to=self.safe_address,
            value=5000000000000000000,  # 5 tokens with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 5)

        # Check the standalone incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(standalone_incoming_erc20.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

        # Test OUTGOING ERC20 from standalone transaction
        standalone_outgoing_erc20 = ERC20TransferFactory(
            address=self.token.address,
            _from=self.safe_address,
            to=self.external_address,
            value=6000000000000000000,  # 6 tokens with 18 decimals
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)

        # Check the standalone outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc20")
        self.assertEqual(result["assetAddress"], self.token.address)
        self.assertEqual(result["assetSymbol"], "TEST")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(standalone_outgoing_erc20.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

    def test_export_view_erc721_transfers(self):
        self._setup_export_tests()
        # Test OUTGOING ERC721 from multisig transaction
        ethereum_tx = EthereumTxFactory()
        multisig_tx = MultisigTransactionFactory(
            safe=self.safe_address, ethereum_tx=ethereum_tx, trusted=True
        )
        multisig_outgoing_erc721_transfer = ERC721TransferFactory(
            ethereum_tx=ethereum_tx,
            address=self.nft_token.address,
            _from=self.safe_address,
            to=self.external_address,
            token_id=123,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(
            result["amount"], str(multisig_outgoing_erc721_transfer.token_id)
        )
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test INCOMING ERC721 from multisig transaction
        ethereum_tx = EthereumTxFactory()
        multisig_tx = MultisigTransactionFactory(
            safe=self.safe_address, ethereum_tx=ethereum_tx, trusted=True
        )
        multisig_incoming_erc721_transfer = ERC721TransferFactory(
            ethereum_tx=ethereum_tx,
            address=self.nft_token.address,
            _from=self.external_address,
            to=self.safe_address,
            token_id=456,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)

        # Check the incoming transaction (should be first in results due to ordering)
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(
            result["amount"], str(multisig_incoming_erc721_transfer.token_id)
        )
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test OUTGOING ERC721 from module transaction
        ethereum_tx_module_out = EthereumTxFactory()
        module_contract_address = Account.create().address
        module_internal_tx_out = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_out, _from=self.safe_address, value=0
        )
        module_transaction_out = ModuleTransactionFactory(
            internal_tx=module_internal_tx_out,
            safe=self.safe_address,
            to=module_contract_address,
        )
        module_outgoing_erc721 = ERC721TransferFactory(
            ethereum_tx=ethereum_tx_module_out,
            address=self.nft_token.address,
            _from=self.safe_address,
            to=self.external_address,
            token_id=789,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 3)

        # Check the module outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(result["amount"], str(module_outgoing_erc721.token_id))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test INCOMING ERC721 from module transaction
        ethereum_tx_module_in = EthereumTxFactory()
        module_internal_tx_in = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_in, _from=self.safe_address, value=0
        )
        module_transaction_in = ModuleTransactionFactory(
            internal_tx=module_internal_tx_in,
            safe=self.safe_address,
            to=module_contract_address,
        )
        module_incoming_erc721 = ERC721TransferFactory(
            ethereum_tx=ethereum_tx_module_in,
            address=self.nft_token.address,
            _from=self.external_address,
            to=self.safe_address,
            token_id=101112,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)
        self.assertEqual(len(response.data["results"]), 4)

        # Check the module incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(result["amount"], str(module_incoming_erc721.token_id))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test INCOMING ERC721 from standalone transaction
        standalone_incoming_erc721 = ERC721TransferFactory(
            address=self.nft_token.address,
            _from=self.external_address,
            to=self.safe_address,
            token_id=131415,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 5)

        # Check the standalone incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(result["amount"], str(standalone_incoming_erc721.token_id))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

        # Test OUTGOING ERC721 from standalone transaction
        standalone_outgoing_erc721 = ERC721TransferFactory(
            address=self.nft_token.address,
            _from=self.safe_address,
            to=self.external_address,
            token_id=161718,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)

        # Check the standalone outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "erc721")
        self.assertEqual(result["assetAddress"], self.nft_token.address)
        self.assertEqual(result["assetSymbol"], "NFT")
        self.assertIsNone(result["assetDecimals"])
        self.assertEqual(result["amount"], str(standalone_outgoing_erc721.token_id))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

    def test_export_view_ether_transfers(self):
        self._setup_export_tests()
        # Test OUTGOING Ether from multisig transaction
        ethereum_tx_multisig_out = EthereumTxFactory()
        value = 1000000000000000000  # 1 ETH
        multisig_tx_out = MultisigTransactionFactory(
            safe=self.safe_address,
            ethereum_tx=ethereum_tx_multisig_out,
            trusted=True,
            to=self.external_address,
            value=value,
        )
        multisig_outgoing_internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx_multisig_out,
            _from=self.safe_address,
            to=self.external_address,
            value=value,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(multisig_outgoing_internal_tx.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test INCOMING Ether from multisig transaction
        ethereum_tx_multisig_in = EthereumTxFactory()
        value = 2000000000000000000
        multisig_tx_in = MultisigTransactionFactory(
            safe=self.safe_address,
            ethereum_tx=ethereum_tx_multisig_in,
            trusted=True,
            value=value,
            to=self.safe_address,
        )
        multisig_incoming_internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx_multisig_in,
            _from=self.external_address,
            to=self.safe_address,
            value=value,  # 2 ETH
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)

        # Check the incoming transaction (should be first in results due to ordering)
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(multisig_incoming_internal_tx.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNotNone(result["safeTxHash"])

        # Test OUTGOING Ether from module transaction
        ethereum_tx_module_out = EthereumTxFactory()
        module_contract_address = Account.create().address
        module_internal_tx_out = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_out,
            _from=self.safe_address,
            to=self.external_address,
            value=3000000000000000000,
        )
        module_transaction_out = ModuleTransactionFactory(
            internal_tx=module_internal_tx_out,
            safe=self.safe_address,
            to=module_contract_address,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 3)

        # Check the module outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(module_internal_tx_out.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test INCOMING Ether from module transaction
        ethereum_tx_module_in = EthereumTxFactory()
        module_internal_tx_in = InternalTxFactory(
            ethereum_tx=ethereum_tx_module_in,
            _from=self.external_address,
            to=self.safe_address,
            value=4000000000000000000,  # 4 ETH
        )
        module_transaction_in = ModuleTransactionFactory(
            internal_tx=module_internal_tx_in,
            safe=self.safe_address,
            to=module_contract_address,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)
        self.assertEqual(len(response.data["results"]), 4)

        # Check the module incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(module_internal_tx_in.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertEqual(result["contractAddress"], module_contract_address)

        # Test OUTGOING Ether from standalone transaction
        standalone_outgoing_internal_tx = InternalTxFactory(
            _from=self.safe_address,
            to=self.external_address,
            value=5000000000000000000,  # 5 ETH
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 5)

        # Check the standalone outgoing transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.safe_address)
        self.assertEqual(result["to"], self.external_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(standalone_outgoing_internal_tx.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

        # Test INCOMING Ether from standalone transaction
        standalone_incoming_internal_tx = InternalTxFactory(
            _from=self.external_address,
            to=self.safe_address,
            value=6000000000000000000,  # 6 ETH
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)

        # Check the standalone incoming transaction
        result = response.json()["results"][0]
        self.assertEqual(result["safe"], self.safe_address)
        self.assertEqual(result["from_"], self.external_address)
        self.assertEqual(result["to"], self.safe_address)
        self.assertEqual(result["assetType"], "native")
        self.assertIsNone(result["assetAddress"])
        self.assertEqual(result["assetSymbol"], "ETH")
        self.assertEqual(result["assetDecimals"], 18)
        self.assertEqual(result["amount"], str(standalone_incoming_internal_tx.value))
        self.assertIsNotNone(result["transactionHash"])
        self.assertIsNone(result["safeTxHash"])
        self.assertIsNone(result["contractAddress"])

    def test_export_view_should_not_include_no_transfer_transactions(self):
        self._setup_export_tests()

        ethereum_tx_multisig = EthereumTxFactory()
        multisig_tx_out = MultisigTransactionFactory(
            safe=self.safe_address,
            ethereum_tx=ethereum_tx_multisig,
            trusted=True,
            to=self.external_address,
            value=0,
        )
        multisig_internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx_multisig,
            _from=self.safe_address,
            to=self.external_address,
            value=0,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(len(response.data["results"]), 0)

        ethereum_tx_multisig = EthereumTxFactory()
        internal_tx = InternalTxFactory(
            ethereum_tx=ethereum_tx_multisig,
            _from=self.safe_address,
            to=self.external_address,
            value=0,
        )
        module_tx = ModuleTransactionFactory(
            internal_tx=internal_tx,
            safe=self.safe_address,
            to=Account.create().address,
        )

        response = self.client.get(
            reverse("v1:history:safe-export", args=(self.safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(len(response.data["results"]), 0)
