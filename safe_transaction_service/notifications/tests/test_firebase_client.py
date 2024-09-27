from unittest import mock

from django.test import TestCase

from firebase_admin import messaging
from firebase_admin.messaging import BatchResponse, SendResponse, UnregisteredError

from ..clients.firebase_client import FirebaseClient, FirebaseClientPool, MockedClient


class TestFirebaseClient(TestCase):
    def test_mocked_client(self):
        mocked_client = MockedClient()
        self.assertIsNone(mocked_client.auth_provider)
        self.assertIsNone(mocked_client.app)
        self.assertFalse(mocked_client.verify_token(""))
        self.assertTrue(mocked_client.verify_token("ab"))

    @mock.patch.object(
        FirebaseClient, "_authenticate", autospec=True, return_value=None
    )
    def test_firebase_client(self, initialize_app_mock):
        try:
            with self.settings(NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS="ab"):
                with FirebaseClientPool() as firebase_client:
                    firebase_client.app = None
                    self.assertNotIsInstance(firebase_client, MockedClient)
                    self.assertIsInstance(
                        firebase_client._build_android_config(), messaging.AndroidConfig
                    )
                    self.assertIsInstance(
                        firebase_client._build_apns_config(), messaging.APNSConfig
                    )
                    with mock.patch(
                        "firebase_admin.messaging.send", return_value=True
                    ) as send_mock:
                        self.assertTrue(firebase_client.verify_token("xy"))
                        send_mock.side_effect = UnregisteredError(
                            "Token not registered"
                        )
                        self.assertFalse(firebase_client.verify_token("xy"))

                    responses = [
                        SendResponse({"name": "id-1"}, None),
                        SendResponse(
                            {"name": "id-2"}, UnregisteredError("Token not registered")
                        ),
                    ]
                    batch_response = BatchResponse(responses)
                    with mock.patch(
                        "firebase_admin.messaging.send_each_for_multicast",
                        return_value=batch_response,
                    ):
                        (
                            success_count,
                            failure_count,
                            invalid_tokens,
                        ) = firebase_client.send_message(
                            ["token-1", "token-2"], {"tx-hash": "0x-random-hash"}
                        )
                        self.assertEqual(success_count, 1)
                        self.assertEqual(failure_count, 1)
                        self.assertEqual(invalid_tokens, ["token-2"])
        finally:
            FirebaseClientPool.firebase_client_pool.clear()
