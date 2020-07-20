from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any, Dict, Sequence, Tuple, Union

from firebase_admin import credentials, initialize_app, messaging
from firebase_admin.exceptions import FirebaseError
from firebase_admin.messaging import BatchResponse

logger = getLogger(__name__)


class FirebaseClientException(Exception):
    pass


class FirebaseTokensNotValid(FirebaseClientException):
    def __init__(self, tokens: Sequence[str]):
        self.tokens = tokens
        super().__init__()


class FirebaseProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance: MessagingClient
            if hasattr(settings, 'NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS'):
                cls.instance: MessagingClient = FirebaseClient(
                    credentials=settings.NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS)
            else:
                logger.warning('Using mocked messaging client')
                cls.instance: MessagingClient = MockedClient()
        return cls.instance


class MessagingClient(ABC):
    @property
    @abstractmethod
    def auth_provider(self):
        pass

    @property
    @abstractmethod
    def app(self):
        return self._app

    @abstractmethod
    def send_message(self, tokens: Sequence[str], data: Dict[str, any]) -> Tuple[int, int]:
        raise NotImplementedError


class FirebaseClient(MessagingClient):
    """
    Wrapper Client for Firebase Cloud Messaging Service
    """
    def __init__(self, credentials_dict: Dict[str, Any]):
        self._credentials = credentials_dict
        self._authenticate()

    def _authenticate(self):
        self._certificate = credentials.Certificate(self._credentials)
        self._app = initialize_app(self._certificate)

    @property
    def auth_provider(self):
        return self._certificate

    @property
    def app(self):
        return self._app

    def _build_android_config(self, title_loc_key: str = ''):
        return messaging.AndroidConfig(
            priority='high',
            # ttl=6*60*60,  # 6 hours
            # notification=messaging.AndroidNotification(
            # title_loc_key=title_loc_key
            # )
        )

    def _build_apns_config(self, title_loc_key: str = ''):
        """
        Data for the Apple Push Notification Service
        see https://firebase.google.com/docs/reference/admin/python/firebase_admin.messaging
        :param title_loc_key:
        :return:
        """

        return messaging.APNSConfig(
            headers={
                'apns-priority': '10'
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    # alert=messaging.ApsAlert(
                    # This is a localized key that iOS will search in
                    # the safe iOS app to show as a default title
                    #    title_loc_key=title_loc_key,
                    # ),
                    # Means the content of the notification will be
                    # modified by the safe app.
                    # Depending on the 'type' custom field,
                    # 'alert.title' and 'alert.body' above will be
                    # different
                    mutable_content=True,
                    badge=1,
                    sound='default',
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
            message = messaging.Message(
                data={},
                token=token
            )
            messaging.send(message, dry_run=True)
            return True
        except FirebaseError:
            return False

    def send_message(self, tokens: Sequence[str], data: Dict[str, any]) -> Tuple[int, int, Sequence[str]]:
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
        batch_response: BatchResponse = messaging.send_multicast(message)
        # Check if there are invalid tokens
        invalid_tokens = [response for response in batch_response.responses
                          if not response.success and isinstance(response.exception, messaging.UnregisteredError)]
        return batch_response.success_count, batch_response.failure_count, invalid_tokens


class MockedClient(MessagingClient):
    @property
    def auth_provider(self):
        return None

    @property
    def app(self):
        return None

    def verify_token(self, token: str) -> bool:
        return bool(token)

    def send_message(self, tokens: Sequence[str], data: Dict[str, any]) -> Tuple[int, int]:
        logger.warning("MockedClient: Not sending message with data=%s and tokens=%s", data, tokens)
        return len(tokens), 0
