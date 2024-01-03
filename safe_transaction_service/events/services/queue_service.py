import json
import logging
from typing import Any, Dict, List, Optional

from django.conf import settings

import pika.exceptions
from pika import BlockingConnection, URLParameters
from pika.adapters.gevent_connection import GeventConnection
from pika.channel import Channel
from pika.exchange_type import ExchangeType

logger = logging.getLogger(__name__)


def getQueueService():
    if settings.EVENTS_QUEUE_URL:
        return SyncQueueService()
    else:
        # Mock send_event to not configured host us is not mandatory configure a queue for events
        return MockedQueueService()
        logger.warning("MockedQueueService is used")


class QueueServicePool:
    """
    Context manager to get a QueueService connection from the pool or create a new one and append it to the pool if all the
    instances are taken. Very useful for gevent, as it is not safe to share one Pika connection across threads.
    https://pika.readthedocs.io/en/stable/faq.html
    Use:
    ```
    with QueueServicePool() as queue_service:
        queue_service...
    ```
    """

    queue_service_pool = []

    def __init__(self):
        self.instance: QueueService

    def __enter__(self):
        if self.queue_service_pool:
            # If there are elements on the pool, take them
            self.instance = self.queue_service_pool.pop()
        else:
            # If not, get a new client
            self.instance = getQueueService()
        return self.instance

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.queue_service_pool.append(self.instance)


class QueueService:
    def __init__(self):
        self.exchange_name: str = settings.EVENTS_QUEUE_EXCHANGE_NAME
        self._channel: Channel = None
        self._connection: GeventConnection = None
        self.unsent_events: List = []
        self._connection_parameters: URLParameters = URLParameters(
            settings.EVENTS_QUEUE_URL
        )

    def send_event(
        self, payload: Dict[str, Any], fail_retry: Optional[bool] = True
    ) -> bool:
        """
        Send an event to rabbitMq exchange

        :param payload: Dict with the payload of the event
        :param fail_retry: if True the unsent event because any error will be retried.
        """
        if self._channel is None or not self._channel.is_open:
            logger.warning("Connection is still not initialized")
            if fail_retry:
                logger.debug("Adding %s to unsent messages", payload)
                self.unsent_events.append(payload)
            # Try to reconnect
            self.connect()
            return False

        try:
            event = json.dumps(payload)
            self._channel.basic_publish(
                exchange=self.exchange_name, routing_key="", body=event
            )
            return True
        except pika.exceptions.AMQPConnectionError:
            logger.warning("Event can not be sent due to there is no channel opened")
            if fail_retry:
                logger.info("Adding %s to unsent messages", payload)
                self.unsent_events.append(payload)
            return False

    def send_unsent_events(self) -> int:
        """
        If connection is ready send the unsent messages list due connection broken

        :return: number of messages sent
        """
        sent_events = 0
        if self._channel.is_open and len(self.unsent_events) > 0:
            logger.info("Sending %i not sent messages", len(self.unsent_events))
            for unsent_message in list(self.unsent_events):
                if self.send_event(unsent_message, fail_retry=False):
                    self.unsent_events.remove(unsent_message)
                    sent_events += 1
                else:
                    break

        return sent_events

    def remove_unsent_events(self):
        self.unsent_events = []


class SyncQueueService(QueueService):
    """
    Synchronous connection with test purpose as we cannot test using gevent connection
    """

    def __init__(self):
        super().__init__()
        self.connect()

    def connect(self) -> BlockingConnection:
        """
        This method connects to RabbitMq using Blockingconnection.
        Store in _connection the BlocingConnection object and creates a new channel

        :return: BlockingConnection
        """
        try:
            self._connection = BlockingConnection(self._connection_parameters)
            self._channel = self.open_channel()
            self._channel.confirm_delivery()
            self.setup_exchange()
            # Send messages if there was any missing
            self.send_unsent_events()
            return self._connection
        except pika.exceptions.AMQPConnectionError:
            logger.error("Cannot open connection, retrying")

    def open_channel(self) -> Channel:
        """
        Open a new channel

        :return: channel opened
        """
        return self._connection.channel()

    def setup_exchange(self):
        """
        Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC
        command.
        """
        logger.info("Declaring exchange %s", self.exchange_name)

        self._channel.exchange_declare(
            exchange=self.exchange_name, exchange_type=ExchangeType.fanout, durable=True
        )


class MockedQueueService:
    """
    Mocked class to use in case that there is not rabbitMq queue to send events
    """

    def send_event(self, event: Dict[str, Any]):
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
