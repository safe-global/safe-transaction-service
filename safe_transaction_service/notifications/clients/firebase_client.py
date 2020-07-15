from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, Union, Any

from firebase_admin import credentials, initialize_app, messaging
from firebase_admin.exceptions import FirebaseError

logger = getLogger(__name__)


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
    def send_message(self, data: Dict[str, any], token: str, ios: bool = True) -> str:
        raise NotImplementedError


class FirebaseClient(MessagingClient):
    # Data for the Apple Push Notification Service
    # see https://firebase.google.com/docs/reference/admin/python/firebase_admin.messaging
    apns = messaging.APNSConfig(
        headers={'apns-priority': '10'},
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(
                    # This is a localized key that iOS will search in
                    # the safe iOS app to show as a default title
                    title_loc_key='sign_transaction_request_title',
                ),
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

    def send_message(self, data: Dict[str, any], token: str, ios: bool = True) -> str:
        """
        Send message using firebase service
        :param data: Dictionary with the notification data
        :param token: Firebase token of recipient
        :param ios: If `True`, `apns` is configured for Apple devices. Otherwise, is not configured and Apple
        devices will not receive the notification
        :return: Firebase `MessageId`
        """
        logger.debug("Sending data=%s with token=%s", data, token)
        message = messaging.Message(
            apns=self.apns if ios else None,
            data=data,
            token=token
        )
        response = messaging.send(message)
        return response


class MockedClient(MessagingClient):
    @property
    def auth_provider(self):
        return None

    @property
    def app(self):
        return None

    def verify_token(self, token: str) -> bool:
        return bool(token)

    def send_message(self, data: Dict[str, any], token: str, ios: bool = True) -> str:
        logger.warning("MockedClient: Not sending message with data %s and token %s", data, token)
        return 'MockedResponse'