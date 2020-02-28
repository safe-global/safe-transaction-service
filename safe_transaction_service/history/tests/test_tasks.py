import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from eth_account import Account

from safe_transaction_service.history.tests.factories import (
    EthereumEventFactory, InternalTxFactory, WebHookFactory)

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
