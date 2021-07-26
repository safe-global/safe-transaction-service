import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests
from eth_account import Account

from gnosis.eth import EthereumClient, EthereumNetwork

from ..models import SafeContract, SafeStatus
from ..tasks import process_decoded_internal_txs_task
from .factories import (EthereumEventFactory, InternalTxDecodedFactory,
                        InternalTxFactory, WebHookFactory)

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    @patch.object(EthereumClient, 'get_network', return_value=EthereumNetwork.GANACHE)
    @patch.object(requests.Session, 'post')
    def test_send_webhook_task(self, mock_post: MagicMock, get_network_mock: MagicMock):
        EthereumEventFactory()

        with self.assertRaises(AssertionError):
            mock_post.assert_called()

        to = Account.create().address
        WebHookFactory(address='')
        WebHookFactory(address=Account.create().address)
        WebHookFactory(address=to)
        InternalTxFactory(to=to)
        # 3 webhooks: INCOMING_ETHER for Webhook with `to`, and then `INCOMING_ETHER` and `OUTGOING_ETHER`
        # for the WebHook without address set
        self.assertEqual(mock_post.call_count, 3)

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
