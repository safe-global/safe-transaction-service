from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from eth_account import Account

from safe_transaction_service.history.tests.factories import EthereumTxFactory
from safe_transaction_service.history.utils import clean_receipt_log

from ..services import AaProcessorService
from .mocks import aa_safe_address, aa_tx_receipt_mock


class TestCommands(TestCase):
    def test_reindex_4337(self):
        command = "reindex_4337"

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Reindexed 0 UserOperations", buf.getvalue())

        # Insert a 4337 transaction
        ethereum_tx = EthereumTxFactory(
            logs=[clean_receipt_log(log) for log in aa_tx_receipt_mock["logs"]]
        )

        # Test command with and without `addresses` flag
        for commands in ([command], [command, f"--addresses={aa_safe_address}"]):
            with mock.patch.object(
                AaProcessorService, "process_aa_transaction", return_value=1
            ) as process_aa_transaction_mock:
                buf = StringIO()
                call_command(*commands, stdout=buf)
                process_aa_transaction_mock.assert_called_once_with(
                    aa_safe_address, ethereum_tx
                )
                self.assertIn("Reindexed 1 UserOperations", buf.getvalue())

        with mock.patch.object(
            AaProcessorService, "process_aa_transaction", return_value=1
        ) as process_aa_transaction_mock:
            buf = StringIO()
            random_address = Account.create().address.lower()  # Test not checksummed
            call_command(command, f"--addresses={random_address}", stdout=buf)
            process_aa_transaction_mock.assert_not_called()
            self.assertIn("Reindexed 0 UserOperations", buf.getvalue())
