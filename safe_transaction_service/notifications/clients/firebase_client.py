from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any, Dict, List, Sequence, Tuple

from django.conf import settings

from firebase_admin import App, credentials, initialize_app, messaging
from firebase_admin.messaging import BatchResponse, SendResponse, UnregisteredError

logger = getLogger(__name__)


def get_firebase_client() -> "MessagingClient":
    """
    Don't use singleton due to gevent. Google Services is keeping the same socket opened. When creating multiple
    instances they need to have a different name, we use an incremental index for that

    :return: New instance of a configured MessagingClient
    """
    if hasattr(settings, "NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS"):
        if not hasattr(get_firebase_client, "created_count"):
            get_firebase_client.created_count = 0
        get_firebase_client.created_count += 1
        created_count = get_firebase_client.created_count
        return FirebaseClient(
            settings.NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS,
            app_name=f"[SAFE-{created_count}]",
        )
    logger.warning("Using mocked messaging client")
    return MockedClient()


class FirebaseClientPool:
    """
    Context manager to get a free FirebaseClient from the pool or create a new one and it to the pool if all the
    instances are taken. Very useful for gevent, as socket cannot be shared between multiple green threads.
    Use:
    ```
    with FirebaseClientPool() as firebase_client:
        firebase_client...
    ```
    """

    firebase_client_pool = []

    def __init__(self):
        self.instance: FirebaseClient

    def __enter__(self):
        if self.firebase_client_pool:
            # If there are elements on the pool, take them
            self.instance = self.firebase_client_pool.pop()
        else:
            # If not, get a new client
            self.instance = get_firebase_client()
        return self.instance

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.firebase_client_pool.append(self.instance)


class MessagingClient(ABC):
    @abstractmethod
    def send_message(
        self, tokens: Sequence[str], data: Dict[str, any]
    ) -> Tuple[int, int, Sequence[str]]:
        raise NotImplementedError


class FirebaseClient(MessagingClient):
    """
    Wrapper Client for Firebase Cloud Messaging Service
    """

    def __init__(self, credentials_dict: Dict[str, Any], app_name: str = "[DEFAULT]"):
        self._credentials = credentials_dict
        self._authenticate(app_name)
        self.app: App

    def _authenticate(self, app_name: str):
        self._certificate = credentials.Certificate(self._credentials)
        self.app = initialize_app(self._certificate, name=app_name)

    @property
    def auth_provider(self):
        return self._certificate

    def _build_android_config(self, title_loc_key: str = ""):
        return messaging.AndroidConfig(
            # priority='high',
            # ttl=6*60*60,  # 6 hours
            # notification=messaging.AndroidNotification(
            # title_loc_key=title_loc_key
            # )
        )

    def _build_apns_config(self, title_loc_key: str = ""):
        """
        Data for the Apple Push Notification Service
        see https://firebase.google.com/docs/reference/admin/python/firebase_admin.messaging

        :param title_loc_key:
        :return:
        """

        return messaging.APNSConfig(
            # headers={
            #    'apns-priority': '10'
            # },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        # This is a localized key that iOS will search in
                        # the safe iOS app to show as a default title
                        title="New Activity",
                        body="New Activity with your Safe",
                        #    title_loc_key=title_loc_key,
                    ),
                    # Means the content of the notification will be
                    # modified by the safe app.
                    # Depending on the 'type' custom field,
                    # 'alert.title' and 'alert.body' above will be
                    # different
                    mutable_content=True,
                    badge=1,
                    sound="default",
                ),
            ),
        )

    def verify_token(self, token: str) -> bool:
        """
        Check if a token is valid on firebase for the project. Only way to do it is simulating a message send

        :param token: Firebase client token
        :return: True if valid, False otherwise
        """
        try:
            message = messaging.Message(data={}, token=token)
            messaging.send(message, dry_run=True, app=self.app)
            return True
        except UnregisteredError:
            return False

    def send_message(
        self, tokens: Sequence[str], data: Dict[str, any]
    ) -> Tuple[int, int, Sequence[str]]:
        """
        Send multicast message using firebase cloud messaging service

        :param tokens: Firebase token of recipient
        :param data: Dictionary with the notification data
        :return: Success count, failure count, invalid tokens
        """
        logger.debug("Sending data=%s with tokens=%s", data, tokens)
        message = messaging.MulticastMessage(
            android=self._build_android_config(),
            apns=self._build_apns_config(),
            data=data,
            tokens=tokens,
        )
        batch_response: BatchResponse = messaging.send_each_for_multicast(
            message, app=self.app
        )
        responses: List[SendResponse] = batch_response.responses
        # Check if there are invalid tokens
        invalid_tokens = [
            token
            for token, response in zip(tokens, responses)
            if not response.success
            and isinstance(response.exception, messaging.UnregisteredError)
        ]
        return (
            batch_response.success_count,
            batch_response.failure_count,
            invalid_tokens,
        )


class MockedClient(MessagingClient):
    @property
    def auth_provider(self):
        return None

    @property
    def app(self):
        return None

    def verify_token(self, token: str) -> bool:
        return bool(token)

    def send_message(
        self, tokens: Sequence[str], data: Dict[str, any]
    ) -> Tuple[int, int, Sequence[str]]:
        logger.warning(
            "MockedClient: Not sending message with data=%s and tokens=%s", data, tokens
        )
        return len(tokens), 0, []
