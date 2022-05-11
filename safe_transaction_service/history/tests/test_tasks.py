import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

import requests
from eth_account import Account

from gnosis.eth import EthereumClient, EthereumNetwork

from ..models import SafeContract, SafeLastStatus, SafeStatus
from ..services import IndexService
from ..tasks import (
    check_reorgs_task,
    check_sync_status_task,
    get_webhook_http_session,
    index_erc20_events_out_of_sync_task,
    index_erc20_events_task,
    index_internal_txs_task,
    index_new_proxies_task,
    index_safe_events_task,
)
from ..tasks import logger as task_logger
from ..tasks import (
    process_decoded_internal_txs_for_safe_task,
    process_decoded_internal_txs_task,
    reindex_last_hours_task,
)
from .factories import (
    ERC20TransferFactory,
    EthereumBlockFactory,
    InternalTxDecodedFactory,
    InternalTxFactory,
    SafeContractFactory,
    SafeStatusFactory,
    WebHookFactory,
)

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    def test_check_reorgs_task(self):
        self.assertIsNone(check_reorgs_task.delay().result, 0)

    def test_check_sync_status_task(self):
        self.assertTrue(check_sync_status_task.delay().result)

    def test_index_erc20_events_task(self):
        self.assertEqual(index_erc20_events_task.delay().result, 0)

    def test_index_erc20_events_out_of_sync_task(self):
        with self.assertLogs(logger=task_logger) as cm:
            index_erc20_events_out_of_sync_task.delay()
            self.assertIn("No addresses to process", cm.output[0])

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract = SafeContractFactory()
            index_erc20_events_out_of_sync_task.delay()
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {[safe_contract.address]}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

    def test_index_internal_txs_task(self):
        self.assertEqual(index_internal_txs_task.delay().result, 0)

    def test_index_new_proxies_task(self):
        self.assertEqual(index_new_proxies_task.delay().result, 0)

    def test_index_safe_events_task(self):
        self.assertEqual(index_safe_events_task.delay().result, 0)

    @patch.object(IndexService, "reindex_master_copies")
    def test_reindex_last_hours_task(self, reindex_master_copies_mock: MagicMock):
        now = timezone.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(weeks=1)

        reindex_last_hours_task()
        reindex_master_copies_mock.assert_not_called()

        ethereum_block_0 = EthereumBlockFactory(timestamp=one_week_ago)
        ethereum_block_1 = EthereumBlockFactory(timestamp=one_day_ago)
        ethereum_block_2 = EthereumBlockFactory(timestamp=one_hour_ago)
        ethereum_block_3 = EthereumBlockFactory(timestamp=now)

        reindex_last_hours_task()
        reindex_master_copies_mock.assert_called_with(
            from_block_number=ethereum_block_1.number,
            to_block_number=ethereum_block_3.number,
        )

    @patch.object(EthereumClient, "get_network", return_value=EthereumNetwork.GANACHE)
    @patch.object(requests.Session, "post")
    def test_send_webhook_task(self, mock_post: MagicMock, get_network_mock: MagicMock):
        ERC20TransferFactory()

        with self.assertRaises(AssertionError):
            mock_post.assert_called()

        to = Account.create().address
        WebHookFactory(address="")
        WebHookFactory(address=Account.create().address)
        WebHookFactory(address=to)
        InternalTxFactory(to=to)
        # 3 webhooks: INCOMING_ETHER for Webhook with `to`, and then `INCOMING_ETHER` and `OUTGOING_ETHER`
        # for the WebHook without address set
        self.assertEqual(mock_post.call_count, 3)

    def test_get_webhook_http_session(self):
        session = get_webhook_http_session("http://random-url", None)
        self.assertNotIn("Authorization", session.headers)

        secret_token = "IDDQD"
        session = get_webhook_http_session("http://random-url", secret_token)
        self.assertEqual(session.headers["Authorization"], secret_token)

    def test_process_decoded_internal_txs_task(self):
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        InternalTxDecodedFactory(
            function_name="setup",
            owner=owner,
            threshold=threshold,
            fallback_handler=fallback_handler,
            internal_tx__to=master_copy,
            internal_tx___from=safe_address,
        )
        process_decoded_internal_txs_task.delay()
        self.assertTrue(SafeContract.objects.get(address=safe_address))
        safe_status = SafeStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.owners, [owner])
        self.assertEqual(safe_status.threshold, threshold)

    def test_process_decoded_internal_txs_for_safe_task(self):
        # Test corrupted SafeStatus
        safe_status_0 = SafeStatusFactory(nonce=0)
        safe_address = safe_status_0.address
        safe_status_2 = SafeStatusFactory(nonce=2, address=safe_address)
        safe_status_5 = SafeStatusFactory(nonce=5, address=safe_address)
        SafeLastStatus.objects.update_or_create_from_safe_status(safe_status_5)
        with patch.object(IndexService, "reindex_master_copies") as reindex_mock:
            with patch.object(IndexService, "reprocess_addresses") as reprocess_mock:
                with self.assertLogs(logger=task_logger) as cm:
                    process_decoded_internal_txs_for_safe_task.delay(safe_address)
                    reprocess_mock.assert_called_with([safe_address])
                    reindex_mock.assert_called_with(
                        from_block_number=safe_status_0.block_number,
                        to_block_number=safe_status_5.block_number,
                    )
                    self.assertIn(
                        f"Safe-address={safe_address} A problem was found in SafeStatus "
                        f"with nonce=2 on internal-tx-id={safe_status_2.internal_tx_id}",
                        cm.output[1],
                    )
                    self.assertIn(
                        f"Safe-address={safe_address} Processing traces again",
                        cm.output[2],
                    )
                    self.assertIn(
                        f"Safe-address={safe_address} Last known not corrupted SafeStatus with nonce=0 on "
                        f"block={safe_status_0.internal_tx.ethereum_tx.block_id} , "
                        f"reindexing until block={safe_status_5.block_number}",
                        cm.output[3],
                    )
                    self.assertIn(
                        f"Reindexing master copies from-block={safe_status_0.internal_tx.ethereum_tx.block_id} "
                        f"to-block={safe_status_5.block_number}",
                        cm.output[4],
                    )
                    self.assertIn(
                        f"Safe-address={safe_address} Processing traces again after reindexing",
                        cm.output[5],
                    )
