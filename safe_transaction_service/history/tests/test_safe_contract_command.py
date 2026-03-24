# SPDX-License-Identifier: FSL-1.1-MIT
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from eth_account import Account

from safe_transaction_service.history.models import SafeContract
from safe_transaction_service.history.services.index_service import (
    TransactionNotFoundException,
)

from .factories import EthereumTxFactory, SafeContractFactory

COMMAND = "safe_contract"
VALID_TX_HASH = "0x" + "ab" * 32

INDEX_SERVICE_PATH = "safe_transaction_service.history.management.commands.safe_contract.IndexServiceProvider"


class TestSafeContractCommand(TestCase):
    def test_no_action_raises(self):
        with self.assertRaisesMessage(CommandError, "Please specify an action"):
            call_command(COMMAND)

    # ------------------------------------------------------------------ add --

    def test_add_invalid_address(self):
        with self.assertRaisesMessage(CommandError, "Invalid Ethereum address"):
            call_command(COMMAND, "add", "not-an-address", VALID_TX_HASH)

    def test_add_invalid_tx_hash_format(self):
        address = Account.create().address
        with self.assertRaisesMessage(CommandError, "Invalid transaction hash"):
            call_command(COMMAND, "add", address, "not-a-hash")

    def test_add_invalid_tx_hash_length(self):
        address = Account.create().address
        short_hash = "0x" + "ab" * 16  # 16 bytes, not 32
        with self.assertRaisesMessage(CommandError, "Invalid transaction hash length"):
            call_command(COMMAND, "add", address, short_hash)

    def test_add_already_exists(self):
        safe_contract = SafeContractFactory()
        buf = StringIO()
        call_command(COMMAND, "add", safe_contract.address, VALID_TX_HASH, stdout=buf)
        self.assertIn("SafeContract already exists", buf.getvalue())

    @patch(INDEX_SERVICE_PATH)
    def test_add_tx_not_found(self, index_service_provider_mock: MagicMock):
        address = Account.create().address
        index_service_provider_mock.return_value.txs_create_or_update_from_tx_hashes.side_effect = TransactionNotFoundException(
            "tx not found"
        )
        with self.assertRaisesMessage(CommandError, "tx not found"):
            call_command(COMMAND, "add", address, VALID_TX_HASH)

    @patch(INDEX_SERVICE_PATH)
    def test_add_success(self, index_service_provider_mock: MagicMock):
        address = Account.create().address
        ethereum_tx = EthereumTxFactory()
        index_service = index_service_provider_mock.return_value
        index_service.txs_create_or_update_from_tx_hashes.return_value = [ethereum_tx]

        buf = StringIO()
        call_command(COMMAND, "add", address, VALID_TX_HASH, stdout=buf)

        self.assertIn("Successfully added SafeContract", buf.getvalue())
        self.assertTrue(SafeContract.objects.filter(address=address).exists())
        index_service.txs_create_or_update_from_tx_hashes.assert_called_once()
        index_service.reindex_master_copies.assert_called_once_with(
            ethereum_tx.block_id, addresses=[address]
        )
        index_service.reindex_erc20_events.assert_called_once_with(
            ethereum_tx.block_id, addresses=[address]
        )

    # --------------------------------------------------------------- remove --

    def test_remove_existing(self):
        safe_contract = SafeContractFactory()
        buf = StringIO()
        call_command(COMMAND, "remove", safe_contract.address, stdout=buf)
        output = buf.getvalue()
        self.assertIn(f"Removed SafeContract: {safe_contract.address}", output)
        self.assertIn("1 removed", output)
        self.assertIn("0 not found", output)
        self.assertFalse(
            SafeContract.objects.filter(address=safe_contract.address).exists()
        )

    def test_remove_not_found(self):
        address = Account.create().address
        buf = StringIO()
        call_command(COMMAND, "remove", address, stdout=buf)
        output = buf.getvalue()
        self.assertIn(f"SafeContract not found: {address}", output)
        self.assertIn("0 removed", output)
        self.assertIn("1 not found", output)

    def test_remove_invalid_address(self):
        with self.assertRaisesMessage(CommandError, "Invalid Ethereum address"):
            call_command(COMMAND, "remove", "bad-address")

    def test_remove_multiple_mixed(self):
        safe_contract = SafeContractFactory()
        missing_address = Account.create().address
        buf = StringIO()
        call_command(
            COMMAND, "remove", safe_contract.address, missing_address, stdout=buf
        )
        output = buf.getvalue()
        self.assertIn(f"Removed SafeContract: {safe_contract.address}", output)
        self.assertIn(f"SafeContract not found: {missing_address}", output)
        self.assertIn("1 removed", output)
        self.assertIn("1 not found", output)
