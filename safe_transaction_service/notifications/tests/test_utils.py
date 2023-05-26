from unittest import TestCase

from safe_transaction_service.utils.redis import get_redis

from ..utils import SafeNotification, mark_notification_as_processed


class TestUtils(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_redis().flushall()

    def tearDown(self):
        super().tearDown()
        get_redis().flushall()

    def test_mark_notification_as_processed(self):
        address = "0x1230B3d59858296A31053C1b8562Ecf89A2f888b"
        payloads = [
            {
                "address": "0x1230B3d59858296A31053C1b8562Ecf89A2f888b",
                "type": "INCOMING_TOKEN",
                "tokenAddress": "0x63704B63Ac04f3a173Dfe677C7e3D330c347CD88",
                "txHash": "0xd8cf5db08e4f3d43660975c8be02a079139a69c42c0ccdd157618aec9bb91b28",
                "value": "50000000000000",
            },
            {
                "address": "0x1230B3d59858296A31053C1b8562Ecf89A2f888b",
                "type": "OUTGOING_TOKEN",
                "tokenAddress": "0x63704B63Ac04f3a173Dfe677C7e3D330c347CD88",
                "txHash": "0xd8cf5db08e4f3d43660975c8be02a079139a69c42c0ccdd157618aec9bb91b28",
                "value": "50000000000000",
            },
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertTrue(mark_notification_as_processed(None, payload))
                self.assertFalse(mark_notification_as_processed(None, payload))
                self.assertTrue(mark_notification_as_processed(address, payload))
                self.assertFalse(mark_notification_as_processed(address, payload))

                self.assertTrue(SafeNotification(None, payload).is_duplicated())
                self.assertTrue(SafeNotification(address, payload).is_duplicated())

        # Change order for fields in `payloads[0]`
        payload_0_changed = {
            "value": "50000000000000",
            "tokenAddress": "0x63704B63Ac04f3a173Dfe677C7e3D330c347CD88",
            "txHash": "0xd8cf5db08e4f3d43660975c8be02a079139a69c42c0ccdd157618aec9bb91b28",
            "address": "0x1230B3d59858296A31053C1b8562Ecf89A2f888b",
            "type": "INCOMING_TOKEN",
        }
        self.assertFalse(mark_notification_as_processed(None, payload_0_changed))
