import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from eth_account import Account

from ..models import SafeContract, SafeStatus
from ..tasks import index_contract_metadata, process_decoded_internal_txs_task
from .factories import (EthereumEventFactory, InternalTxDecodedFactory,
                        InternalTxFactory, MultisigTransactionFactory,
                        WebHookFactory)

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

    def test_index_contract_metadata(self):
        self.assertEqual(index_contract_metadata.delay().result, 0)
        [MultisigTransactionFactory(to=Account.create().address, data=b'12') for _ in range(2)]
        self.assertEqual(index_contract_metadata.delay().result, 2)
        self.assertEqual(index_contract_metadata.delay().result, 0)
