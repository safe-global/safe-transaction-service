import json
import logging
from dataclasses import asdict
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
from requests import ReadTimeout
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.ethereum_client import EthereumClient, ParityManager
from gnosis.eth.utils import fast_is_checksum_address
from gnosis.safe import CannotEstimateGas, Safe, SafeOperation
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType
from gnosis.safe.signatures import signature_to_bytes
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.contracts.models import ContractQuerySet
from safe_transaction_service.contracts.tests.factories import ContractFactory
from safe_transaction_service.contracts.tx_decoder import DbTxDecoder
from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.services.price_service import PriceService
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..helpers import DelegateSignatureHelper
from ..models import (
    IndexingStatus,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContractDelegate,
    SafeMasterCopy,
)
from ..serializers import TransferType
from ..services import BalanceService, CollectiblesService
from ..services.balance_service import Erc20InfoWithLogo
from ..services.collectibles_service import CollectibleWithMetadata
from ..views import SafeMultisigTransactionListView
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
from .mocks.traces import call_trace

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_about_view(self):
        url = reverse("v1:history:about")
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
        "current_block_number",
        new_callable=PropertyMock,
        return_value=2000,
    )
    def test_erc20_indexing_view(self, current_block_number_mock: PropertyMock):
        IndexingStatus.objects.set_erc20_721_indexing_status(2_000)
        url = reverse("v1:history:erc20-indexing")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2_000)
        self.assertEqual(response.data["erc20_block_number"], 2_000)
        self.assertEqual(response.data["erc20_synced"], True)

        IndexingStatus.objects.set_erc20_721_indexing_status(10)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2_000)
        self.assertEqual(response.data["erc20_block_number"], 10)
        self.assertEqual(response.data["erc20_synced"], False)

    @mock.patch.object(
        EthereumClient,
        "current_block_number",
        new_callable=PropertyMock,
        return_value=2_000,
    )
    def test_indexing_view(self, current_block_number_mock: PropertyMock):
        IndexingStatus.objects.set_erc20_721_indexing_status(2_000)
        url = reverse("v1:history:indexing")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2_000)
        self.assertEqual(response.data["erc20_block_number"], 2_000)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 2_000)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], True)

        IndexingStatus.objects.set_erc20_721_indexing_status(500)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 500)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 2000)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], False)

        safe_master_copy = SafeMasterCopyFactory(tx_block_number=1999)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 500)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 1999)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], False)

        safe_master_copy.tx_block_number = 600
        safe_master_copy.save(update_fields=["tx_block_number"])
        response = self.client.get(url, format="json")
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 500)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 600)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)

        IndexingStatus.objects.set_erc20_721_indexing_status(10)
        SafeMasterCopyFactory(tx_block_number=9)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 10)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 9)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)

        SafeMasterCopyFactory(tx_block_number=11)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 10)
        self.assertEqual(response.data["erc20_synced"], False)
        self.assertEqual(response.data["master_copies_block_number"], 9)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)

        IndexingStatus.objects.set_erc20_721_indexing_status(1_999)
        SafeMasterCopy.objects.update(tx_block_number=1999)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 1999)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 1999)
        self.assertEqual(response.data["master_copies_synced"], True)
        self.assertEqual(response.data["synced"], True)

        SafeMasterCopyFactory(tx_block_number=48)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current_block_number"], 2000)
        self.assertEqual(response.data["erc20_block_number"], 1999)
        self.assertEqual(response.data["erc20_synced"], True)
        self.assertEqual(response.data["master_copies_block_number"], 48)
        self.assertEqual(response.data["master_copies_synced"], False)
        self.assertEqual(response.data["synced"], False)

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

        # Should not appear unless queued=True, nonce > last mined transaction
        higher_nonce_safe_multisig_transaction = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx=None
        )
        higher_nonce_safe_multisig_transaction_2 = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx=None
        )

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=True&trusted=True"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=True&trusted=False"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 8)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=False"
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
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?limit=3&queued=False&trusted=False"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 3)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?limit=4&offset=4&queued=False&trusted=False"
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
            + "?queued=False&trusted=False"
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
        # Mine tx with higher nonce, all should appear
        MultisigTransactionFactory(safe=safe_address)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?executed=False&queued=True&trusted=False"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)

        response = self.client.get(
            reverse("v1:history:all-transactions", args=(safe_address,))
            + "?executed=True&queued=True&trusted=False"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

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

    def test_get_multisig_confirmation(self):
        random_safe_tx_hash = Web3.keccak(text="enxebre").hex()
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
        random_safe_tx_hash = Web3.keccak(text="enxebre").hex()
        data = {
            "signature": Account.create()
            .signHash(random_safe_tx_hash)["signature"]
            .hex()  # Not valid signature
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
            "signature": random_account.signHash(safe_tx_hash)[
                "signature"
            ].hex()  # Not valid signature
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

        data = {"signature": owner_account_1.signHash(safe_tx_hash)["signature"].hex()}
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
            "signature": (
                owner_account_1.signHash(safe_tx_hash)["signature"]
                + owner_account_2.signHash(safe_tx_hash)["signature"]
            ).hex()
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

    def test_get_multisig_transaction(self):
        safe_tx_hash = Web3.keccak(text="gnosis").hex()
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
        multisig_tx = MultisigTransactionFactory(data=add_owner_with_threshold_data)
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

    def test_get_multisig_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        multisig_tx = MultisigTransactionFactory(safe=safe_address)
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

        MultisigTransactionFactory(safe=safe_address, nonce=multisig_tx.nonce)
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["count_unique_nonce"], 1)

    @mock.patch.object(
        DbTxDecoder, "get_data_decoded", return_value={"param1": "value"}
    )
    def test_get_multisig_transactions_not_decoded(
        self, get_data_decoded_mock: MagicMock
    ):
        try:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            multisig_transaction = MultisigTransactionFactory(
                operation=SafeOperation.CALL.value, data=b"abcd"
            )
            safe_address = multisig_transaction.safe
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data["results"][0]["data_decoded"], {"param1": "value"}
            )

            multisig_transaction.operation = SafeOperation.DELEGATE_CALL.value
            multisig_transaction.save()
            response = self.client.get(
                reverse("v1:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIsNone(response.data["results"][0]["data_decoded"])

            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            ContractFactory(
                address=multisig_transaction.to, trusted_for_delegate_call=True
            )
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
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address, nonce=0, ethereum_tx=None
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

        MultisigConfirmationFactory(multisig_transaction=multisig_transaction)
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["results"][0]["executor"])
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 0)

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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["results"][0]["executor"])
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 0)

        # Test confirmation with signature
        data["signature"] = safe_owner_1.signHash(safe_tx.safe_tx_hash)[
            "signature"
        ].hex()
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
        data["signature"] = random_user_account.signHash(safe_tx.safe_tx_hash)[
            "signature"
        ].hex()
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()

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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
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
        data["contractTransactionHash"] = safe_tx.safe_tx_hash.hex()
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
        data["contractTransactionHash"] = safe_tx_hash.hex()
        data["signature"] = b"".join(
            [
                safe_owner.signHash(safe_tx_hash)["signature"]
                for safe_owner in safe_owners
            ]
        ).hex()
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
        data["contractTransactionHash"] = safe_tx_hash.hex()
        data["signature"] = safe_delegate.signHash(safe_tx_hash)["signature"].hex()

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

        # Add delegate
        SafeContractDelegateFactory(
            safe_contract__address=safe_address,
            delegate=safe_delegate.address,
            delegator=safe_owners[0].address,
        )
        response = self.client.post(
            reverse("v1:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        self.assertTrue(MultisigTransaction.objects.first().trusted)

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

    @mock.patch.object(BalanceService, "get_token_info", autospec=True)
    @mock.patch.object(
        PriceService, "get_token_eth_value", return_value=0.4, autospec=True
    )
    @mock.patch.object(
        PriceService, "get_native_coin_usd_price", return_value=123.4, autospec=True
    )
    @mock.patch.object(timezone, "now", return_value=timezone.now())
    def test_safe_balances_usd_view(
        self,
        timezone_now_mock: MagicMock,
        get_native_coin_usd_price_mock: MagicMock,
        get_token_eth_value_mock: MagicMock,
        get_token_info_mock: MagicMock,
    ):
        timestamp_str = timezone_now_mock.return_value.isoformat().replace(
            "+00:00", "Z"
        )
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-balances-usd", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(
            reverse("v1:history:safe-balances-usd", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIsNone(response.data[0]["token_address"])
        self.assertEqual(response.data[0]["balance"], str(value))
        self.assertEqual(response.data[0]["eth_value"], "1.0")

        tokens_value = int(12 * 1e18)
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(
            reverse("v1:history:safe-balances-usd", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        erc20_info = Erc20InfoWithLogo(
            erc20.address, "UXIO", "UXI", 18, None, "http://logo_uri.es"
        )
        get_token_info_mock.return_value = erc20_info

        ERC20TransferFactory(address=erc20.address, to=safe_address)
        response = self.client.get(
            reverse("v1:history:safe-balances-usd", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token_dict = asdict(erc20_info)
        del token_dict["address"]
        del token_dict["copy_price"]
        self.assertCountEqual(
            response.data,
            [
                {
                    "token_address": None,
                    "token": None,
                    "balance": str(value),
                    "eth_value": "1.0",
                    "timestamp": timestamp_str,
                    "fiat_balance": "0.0",
                    "fiat_conversion": "123.4",
                    "fiat_code": "USD",
                },  # 7 wei is rounded to 0.0
                {
                    "token_address": erc20.address,
                    "token": token_dict,
                    "balance": str(tokens_value),
                    "eth_value": "0.4",
                    "timestamp": timestamp_str,
                    "fiat_balance": str(round(123.4 * 0.4 * (tokens_value / 1e18), 4)),
                    "fiat_conversion": str(round(123.4 * 0.4, 4)),
                    "fiat_code": "USD",
                },
            ],
        )

    # Test without pagination
    def test_safe_collectibles(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-collectibles", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.get(
            reverse("v1:history:safe-collectibles", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

        with mock.patch.object(
            CollectiblesService, "get_collectibles_with_metadata", autospec=True
        ) as function:
            token_name = "TokenName"
            token_symbol = "SYMBOL"
            token_address = Account.create().address
            logo_uri = f"http://token.org/{token_address}.png"
            token_id = 54
            token_uri = f"http://token.org/token-id/{token_id}"
            image = "http://token.org/token-id/1/image"
            name = "Test token name"
            description = "Test token description"
            function.return_value = [
                CollectibleWithMetadata(
                    token_name,
                    token_symbol,
                    logo_uri,
                    token_address,
                    token_id,
                    token_uri,
                    {"image": image, "name": name, "description": description},
                )
            ]
            response = self.client.get(
                reverse("v1:history:safe-collectibles", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data,
                [
                    {
                        "address": token_address,
                        "token_name": token_name,
                        "token_symbol": token_symbol,
                        "logo_uri": logo_uri,
                        "id": str(token_id),
                        "uri": token_uri,
                        "name": name,
                        "description": description,
                        "image_uri": image,
                        "metadata": {
                            "image": image,
                            "name": name,
                            "description": description,
                        },
                    }
                ],
            )

    def test_get_safe_delegate_list(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        safe_contract_delegate = SafeContractDelegateFactory()
        safe_address = safe_contract_delegate.safe_contract_id
        response = self.client.get(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["count"], 1)
        result = response.data["results"][0]
        self.assertEqual(result["delegate"], safe_contract_delegate.delegate)
        self.assertEqual(result["delegator"], safe_contract_delegate.delegator)
        self.assertEqual(result["label"], safe_contract_delegate.label)

        safe_contract_delegate = SafeContractDelegateFactory(
            safe_contract=safe_contract_delegate.safe_contract
        )
        response = self.client.get(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

        # A different non related Safe should not increase the number
        SafeContractDelegateFactory()
        response = self.client.get(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_delete_safe_delegate_list(self):
        endpoint = "v1:history:safe-delegates"

        owner_account = Account.create()
        safe_address = self.deploy_test_safe(owners=[owner_account.address]).address
        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.delete(
            reverse(endpoint, args=(safe_address,)), format="json"
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST
        )  # Data is missing

        data = {
            "signature": "0x" + "1" * 130,
        }
        not_existing_safe = Account.create().address
        response = self.client.delete(
            reverse(endpoint, args=(not_existing_safe,)), format="json", data=data
        )
        self.assertIn(
            f"Safe={not_existing_safe} does not exist",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        hash_to_sign = DelegateSignatureHelper.calculate_hash(
            safe_address, eth_sign=True
        )
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        SafeContractDelegateFactory(safe_contract=safe_contract)
        SafeContractDelegateFactory(safe_contract=safe_contract)
        SafeContractDelegateFactory(safe_contract=SafeContractFactory())
        self.assertEqual(SafeContractDelegate.objects.count(), 3)
        response = self.client.delete(
            reverse(endpoint, args=(safe_address,)), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)

        # Sign random address instead of the Safe address
        hash_to_sign = DelegateSignatureHelper.calculate_hash(
            Account.create().address, eth_sign=True
        )
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        response = self.client.delete(
            reverse(endpoint, args=(safe_address,)), format="json", data=data
        )
        self.assertIn(
            "Signing owner is not an owner of the Safe",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_safe_delegate(self):
        safe_address = Account.create().address
        delegate_address = Account.create().address
        label = "Saul Goodman"
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST
        )  # Data is missing

        data = {
            "delegate": delegate_address,
            "label": label,
            "signature": "0x" + "1" * 130,
        }

        owner_account = Account.create()
        safe_address = self.deploy_test_safe(owners=[owner_account.address]).address
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Safe={safe_address} does not exist", response.data["non_field_errors"][0]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            "Signing owner is not an owner of the Safe",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(SafeContractDelegate.objects.count(), 0)
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address)
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        safe_contract_delegate = SafeContractDelegate.objects.first()
        self.assertEqual(safe_contract_delegate.delegate, delegate_address)
        self.assertEqual(safe_contract_delegate.delegator, owner_account.address)
        self.assertEqual(safe_contract_delegate.label, label)

        label = "Jimmy McGill"
        data["label"] = label
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        safe_contract_delegate.refresh_from_db()
        self.assertEqual(safe_contract_delegate.label, label)

        another_label = "Kim Wexler"
        another_delegate_address = Account.create().address
        data = {
            "delegate": another_delegate_address,
            "label": another_label,
            "signature": owner_account.signHash(
                DelegateSignatureHelper.calculate_hash(
                    another_delegate_address, eth_sign=True
                )
            )["signature"].hex(),
        }
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Test not internal server error on contract signature
        signature = signature_to_bytes(
            0, int(owner_account.address, 16), 65
        ) + HexBytes("0" * 65)
        data["signature"] = signature.hex()
        response = self.client.post(
            reverse("v1:history:safe-delegates", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(
            reverse("v1:history:safe-delegates", args=(safe_address,)), format="json"
        )
        self.assertCountEqual(
            response.data["results"],
            [
                {
                    "delegate": delegate_address,
                    "delegator": owner_account.address,
                    "label": label,
                    "safe": safe_address,
                },
                {
                    "delegate": another_delegate_address,
                    "delegator": owner_account.address,
                    "label": another_label,
                    "safe": safe_address,
                },
            ],
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        self.assertCountEqual(
            SafeContractDelegate.objects.get_delegates_for_safe(safe_address),
            [delegate_address, another_delegate_address],
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
            data["signature"] = delegator.signHash(hash_to_sign)["signature"].hex()
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.delegate, delegate.address)
            self.assertEqual(safe_contract_delegate.delegator, delegator.address)
            self.assertEqual(safe_contract_delegate.label, label)
            self.assertEqual(safe_contract_delegate.safe_contract_id, safe_address)

            # Update label
            label = "Jimmy McGill"
            data["label"] = label
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(SafeContractDelegate.objects.count(), 1)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.label, label)

        # Create delegate without a Safe
        another_label = "Kim Wexler"
        data = {
            "label": another_label,
            "delegate": delegate.address,
            "delegator": delegator.address,
            "safe": None,
            "signature": delegator.signHash(
                DelegateSignatureHelper.calculate_hash(delegate.address, eth_sign=True)
            )["signature"].hex(),
        }
        response = self.client.post(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)

        # Test not internal server error on contract signature
        signature = signature_to_bytes(0, int(delegator.address, 16), 65) + HexBytes(
            "0" * 65
        )
        data["signature"] = signature.hex()
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Signature of type=CONTRACT_SIGNATURE for delegator={delegator.address} is not valid",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        self.assertCountEqual(
            SafeContractDelegate.objects.get_delegates_for_safe(safe_address),
            [delegate.address],
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
            },
            {
                "delegate": safe_contract_delegate_2.delegate,
                "delegator": safe_contract_delegate_2.delegator,
                "label": safe_contract_delegate_2.label,
                "safe": safe_contract.address,
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
            },
            {
                "delegate": safe_contract_delegate_3.delegate,
                "delegator": safe_contract_delegate_3.delegator,
                "label": safe_contract_delegate_3.label,
                "safe": safe_contract_delegate_3.safe_contract_id,
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
                    "signature": signer.signHash(hash_to_sign)["signature"].hex(),
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
            "signature": signer.signHash(hash_to_sign)["signature"].hex(),
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
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Not found", response.data["detail"])

        # Test previous otp
        hash_to_sign = DelegateSignatureHelper.calculate_hash(
            delegate_address, previous_totp=True
        )
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Not found", response.data["detail"])

        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address)
        data["signature"] = owner_account.signHash(hash_to_sign)["signature"].hex()
        response = self.client.delete(
            reverse("v1:history:safe-delegate", args=(safe_address, delegate_address)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Not found", response.data["detail"])

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
        data["signature"] = delegate_account.signHash(hash_to_sign)["signature"].hex()
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
        internal_tx = InternalTxFactory(to=safe_address, value=value)
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
        ethereum_erc_20_event = ERC20TransferFactory(to=safe_address, value=token_value)
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
                    "executionDate": ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
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
                    },
                },
                {
                    "type": TransferType.ETHER_TRANSFER.name,
                    "executionDate": internal_tx.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
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
        ethereum_erc_721_event = ERC721TransferFactory(
            to=safe_address, token_id=token_id
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
                    "executionDate": ethereum_erc_721_event.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
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
                    "executionDate": ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
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
                    },
                },
                {
                    "type": TransferType.ETHER_TRANSFER.name,
                    "executionDate": internal_tx.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
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
        internal_tx = InternalTxFactory(to=safe_address, value=value)
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
        internal_tx_2 = InternalTxFactory(_from=safe_address, value=value)
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["value"], str(value))
        self.assertEqual(response.data["results"][1]["value"], str(value))

        token_value = 6
        ethereum_erc_20_event = ERC20TransferFactory(to=safe_address, value=token_value)
        ethereum_erc_20_event_2 = ERC20TransferFactory(
            _from=safe_address, value=token_value
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
                "executionDate": ethereum_erc_20_event_2.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "blockNumber": ethereum_erc_20_event_2.ethereum_tx.block_id,
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
                "executionDate": ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "blockNumber": ethereum_erc_20_event.ethereum_tx.block_id,
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
                },
            },
            {
                "type": TransferType.ETHER_TRANSFER.name,
                "executionDate": internal_tx_2.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "blockNumber": internal_tx_2.ethereum_tx.block_id,
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
                "executionDate": internal_tx.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "blockNumber": internal_tx.ethereum_tx.block_id,
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
        ethereum_erc_721_event = ERC721TransferFactory(
            to=safe_address, token_id=token_id
        )
        ethereum_erc_721_event_2 = ERC721TransferFactory(
            _from=safe_address, token_id=token_id
        )
        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        expected_results = [
            {
                "type": TransferType.ERC721_TRANSFER.name,
                "executionDate": ethereum_erc_721_event_2.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "transactionHash": ethereum_erc_721_event_2.ethereum_tx_id,
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
                "executionDate": ethereum_erc_721_event.ethereum_tx.block.timestamp.isoformat().replace(
                    "+00:00", "Z"
                ),
                "transactionHash": ethereum_erc_721_event.ethereum_tx_id,
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

        response = self.client.get(
            reverse("v1:history:transfers", args=(safe_address,)) + "?ether=false",
            format="json",
        )
        self.assertGreater(len(response.data["results"]), 0)
        for result in response.data["results"]:
            self.assertNotEqual(result["type"], TransferType.ETHER_TRANSFER.name)

    def test_safe_creation_view(self):
        invalid_address = "0x2A"
        response = self.client.get(
            reverse("v1:history:safe-creation", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(
            reverse("v1:history:safe-creation", args=(owner_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        with mock.patch.object(
            ParityManager, "trace_transaction", autospec=True, return_value=[]
        ):
            # Insert create contract internal tx
            internal_tx = InternalTxFactory(
                contract_address=owner_address,
                trace_address="0,0",
                ethereum_tx__status=1,
            )
            response = self.client.get(
                reverse("v1:history:safe-creation", args=(owner_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            created_iso = internal_tx.ethereum_tx.block.timestamp.isoformat().replace(
                "+00:00", "Z"
            )
            expected = {
                "created": created_iso,
                "creator": internal_tx.ethereum_tx._from,
                "factory_address": internal_tx._from,
                "master_copy": None,
                "setup_data": None,
                "data_decoded": None,
                "transaction_hash": internal_tx.ethereum_tx_id,
            }
            self.assertEqual(response.data, expected)

        # Next children internal_tx should not alter the result
        another_trace = dict(call_trace)
        another_trace["traceAddress"] = [0, 0, 0]
        with mock.patch.object(
            ParityManager,
            "trace_transaction",
            autospec=True,
            return_value=[another_trace],
        ):
            response = self.client.get(
                reverse("v1:history:safe-creation", args=(owner_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, expected)

        another_trace_2 = dict(call_trace)
        another_trace_2["traceAddress"] = [0]
        with mock.patch.object(
            ParityManager,
            "trace_transaction",
            autospec=True,
            return_value=[another_trace, another_trace_2],
        ):
            # `another_trace_2` should change the `creator` and `master_copy` and `setup_data` should appear
            # Taken from rinkeby
            create_test_data = {
                "master_copy": "0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A",
                "setup_data": "0xa97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba134080000000000000000000000000000000000000000000000000000000000000000",
                "data": "0x61b69abd000000000000000000000000b6029ea3b2c51d09a50b53ca8012feeb05bda35a00000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000000000000000000000000184a97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba13408000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            }
            data_decoded_1 = {
                "method": "setup",
                "parameters": [
                    {
                        "name": "_owners",
                        "type": "address[]",
                        "value": [
                            "0x6E45d69a383CECa3d54688e833Bd0e1388747e6B",
                            "0x61a0c717d18232711bC788F19C9Cd56a43cc8872",
                            "0x7724b234c9099C205F03b458944942bcEBA13408",
                        ],
                    },
                    {"name": "_threshold", "type": "uint256", "value": "1"},
                    {
                        "name": "to",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                    {"name": "data", "type": "bytes", "value": "0x"},
                    {
                        "name": "paymentToken",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                    {"name": "payment", "type": "uint256", "value": "0"},
                    {
                        "name": "paymentReceiver",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                ],
            }

            create_test_data_2 = {
                "master_copy": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
                "setup_data": "0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
                "data": "0x1688f0b900000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f0000000000000000000000000000000000000000000000000000000000000060000000000000000000000000000000000000000000000000000002cecc9e861200000000000000000000000000000000000000000000000000000000000001c4b63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            }
            data_decoded_2 = {
                "method": "setup",
                "parameters": [
                    {
                        "name": "_owners",
                        "type": "address[]",
                        "value": [
                            "0x85C26101f353f38E45c72d414b44972831f07BE3",
                            "0x235518798770D7336c5c4908dd1019457FEa43a1",
                            "0x7F63c25665EA7e85500eAEB806E552e651B07b9d",
                        ],
                    },
                    {"name": "_threshold", "type": "uint256", "value": "1"},
                    {
                        "name": "to",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                    {"name": "data", "type": "bytes", "value": "0x"},
                    {
                        "name": "fallbackHandler",
                        "type": "address",
                        "value": "0xd5D82B6aDDc9027B22dCA772Aa68D5d74cdBdF44",
                    },
                    {
                        "name": "paymentToken",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                    {"name": "payment", "type": "uint256", "value": "3036537000337393"},
                    {
                        "name": "paymentReceiver",
                        "type": "address",
                        "value": "0x0000000000000000000000000000000000000000",
                    },
                ],
            }

            create_cpk_test_data = {
                "master_copy": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
                "setup_data": "0x5714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a80620074",
                "data": "0x460868ca00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5fcfe33a586323e7325be6aa6ecd8b4600d232a9037e83c8ece69413b777dabe6500000000000000000000000040a930851bd2e590bd5a5c981b436de25742e9800000000000000000000000005ef44de4b98f2bce0e29c344e7b2fb8f0282a0cf000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000e0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000245714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a8062007400000000000000000000000000000000000000000000000000000000",
            }
            data_decoded_cpk = None

            for test_data, data_decoded in [
                (create_test_data, data_decoded_1),
                (create_test_data_2, data_decoded_2),
                (create_cpk_test_data, data_decoded_cpk),
            ]:
                another_trace_2["action"]["input"] = HexBytes(test_data["data"])
                response = self.client.get(
                    reverse("v1:history:safe-creation", args=(owner_address,)),
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                created_iso = (
                    internal_tx.ethereum_tx.block.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    )
                )
                self.assertEqual(
                    response.data,
                    {
                        "created": created_iso,
                        "creator": another_trace_2["action"]["from"],
                        "transaction_hash": internal_tx.ethereum_tx_id,
                        "factory_address": internal_tx._from,
                        "master_copy": test_data["master_copy"],
                        "setup_data": test_data["setup_data"],
                        "data_decoded": data_decoded,
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
                "nonce": 0,
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

    def test_master_copies_view(self):
        response = self.client.get(reverse("v1:history:master-copies"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        deployed_block_number = 2
        last_indexed_block_number = 5
        safe_master_copy = SafeMasterCopyFactory(
            initial_block_number=deployed_block_number,
            tx_block_number=last_indexed_block_number,
        )
        response = self.client.get(reverse("v1:history:master-copies"))
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
        response = self.client.get(reverse("v1:history:master-copies"))
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
            response = self.client.get(reverse("v1:history:master-copies"))
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertCountEqual(response.data, expected_l2_master_copy)

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
            data={"data": add_owner_with_threshold_data.hex()},
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
