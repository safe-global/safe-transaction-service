import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from eth_account import Account

from ..models import SafeContract, SafeStatus
from ..tasks import (BlockchainRunningTask, BlockchainRunningTaskManager,
                     process_decoded_internal_txs_task)
from .factories import (EthereumEventFactory, InternalTxDecodedFactory,
                        InternalTxFactory, WebHookFactory)

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    @patch('requests.post')
    def test_send_webhook_task(self, mock_post: MagicMock):
        EthereumEventFactory()

        with self.assertRaises(AssertionError):
            mock_post.assert_called()

        to = Account.create().address
        WebHookFactory(address='')
        WebHookFactory(address=Account.create().address)
        WebHookFactory(address=to)
        InternalTxFactory(to=to)
        self.assertEqual(mock_post.call_count, 2)

    def test_blockchain_running_task(self):
        # Test context manager
        class A:
            def __init__(self, id: str):
                self.id = id

        BlockchainRunningTaskManager().delete_all_tasks()
        a = A('custom-task-id')
        b = A('another-task_id')
        with BlockchainRunningTask(a) as blockchain_running_task:
            self.assertEqual(blockchain_running_task.blockchain_running_task_manager.get_running_tasks(),
                             [a.id])
            with BlockchainRunningTask(b):
                self.assertEqual(blockchain_running_task.blockchain_running_task_manager.get_running_tasks(),
                                 [b.id, a.id])

        self.assertEqual(BlockchainRunningTaskManager().get_running_tasks(), [])

    def test_process_decoded_internal_txs_task(self):
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        InternalTxDecodedFactory(function_name='setup', owner=owner, threshold=threshold,
                                 fallback_handler=fallback_handler,
                                 internal_tx__to=master_copy,
                                 internal_tx___from=safe_address)
        process_decoded_internal_txs_task.delay()
        self.assertTrue(SafeContract.objects.get(address=safe_address))
        safe_status = SafeStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.owners, [owner])
        self.assertEqual(safe_status.threshold, threshold)