import json
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

from django.conf import settings

import pika.exceptions
from pika import BlockingConnection, URLParameters
from pika.channel import Channel
from pika.exchange_type import ExchangeType

logger = logging.getLogger(__name__)


class BrokerConnection:
    def __init__(self):
        self.exchange_name: str = settings.EVENTS_QUEUE_EXCHANGE_NAME
        self.channel: Channel = None
        self._connection_parameters = URLParameters(settings.EVENTS_QUEUE_URL)
        self.connection: BlockingConnection = self.connect()

    def connect(self) -> Optional[BlockingConnection]:
        """
        This method connects to RabbitMq using Blockingconnection.
        Store in _connection the BlocingConnection object and creates a new channel

        :return: BlockingConnection
        """
        try:
            self.connection = BlockingConnection(self._connection_parameters)
            self.channel = self.connection.channel()
            self.channel.confirm_delivery()
            # Declare exchange
            self.channel.exchange_declare(
                exchange=self.exchange_name,
                exchange_type=ExchangeType.fanout,
                durable=True,
            )
            # Send messages if there was any missing
            # self.send_unsent_events()
            return self.connection
        except pika.exceptions.AMQPConnectionError:
            logger.error("Cannot open connection with RabbitMQ")

    def is_connected(self) -> bool:
        if not self.connection or not self.connection.is_open:
            return False
        return True

    def publish(self, message: str) -> bool:
        # Check if is still connected if not try to reconnect
        if not self.is_connected() and not self.connect():
            return False
        try:
            self.channel.basic_publish(
                exchange=self.exchange_name, routing_key="", body=message
            )
            return True
        except pika.exceptions.AMQPConnectionError:
            return False


@lru_cache
def getQueueService():
    if settings.EVENTS_QUEUE_URL:
        return QueueService()
    else:
        # Mock send_event to not configured host us is not mandatory configure a queue for events
        return MockedQueueService()
        logger.warning("MockedQueueService is used")


class QueueService:
    def __init__(self):
        self._connections_pool: List[BrokerConnection] = []
        self.unsent_events: List = []

    def get_connection(self) -> BrokerConnection:
        if self._connections_pool:
            return self._connections_pool.pop()
        else:
            return BrokerConnection()

    def release_connection(self, broker_connection: BrokerConnection):
        self._connections_pool.insert(0, broker_connection)

    def send_event(self, payload: Dict[str, Any]) -> int:
        """
        Send an event to rabbitMq exchange

        :param payload: Dict with the payload of the event
        """
        broker_connection = self.get_connection()

        event = json.dumps(payload)
        if broker_connection.publish(event):
            self.release_connection(broker_connection)
            return self.send_unsent_events() + 1
        else:
            logger.warning("Event can not be sent due any connection error")
            logger.debug("Adding %s to unsent messages", payload)
            self.unsent_events.append(event)

        self.release_connection(broker_connection)
        return 0

    def send_unsent_events(self) -> int:
        """
        If connection is ready send the unsent messages list due connection broken

        :return: number of messages sent
        """
        if len(self.unsent_events):
            broker_connection = self.get_connection()
            sent_events = 0
            logger.info("Sending %i not sent messages", len(self.unsent_events))
            for unsent_message in list(self.unsent_events):
                if broker_connection.publish(unsent_message):
                    self.unsent_events.remove(unsent_message)
                    sent_events += 1
                else:
                    break
            self.release_connection(broker_connection)
            return sent_events
        return 0

    def remove_unsent_events(self):
        self.unsent_events = []


class MockedQueueService:
    """
    Mocked class to use in case that there is not rabbitMq queue to send events
    """

    def send_event(self, event: Dict[str, Any]):
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
