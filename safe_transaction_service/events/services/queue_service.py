import json
import logging
from functools import cache
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
        self.channel: Optional[Channel] = None
        self.connection_parameters = URLParameters(settings.EVENTS_QUEUE_URL)
        self.connection: Optional[BlockingConnection] = self.connect()

    def connect(self) -> Optional[BlockingConnection]:
        """
        This method connects to RabbitMq using BlockingConnection.

        :return: BlockingConnection
        """
        try:
            logger.debug("Opening connection to RabbitMQ")
            self.connection = BlockingConnection(self.connection_parameters)
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
            logger.debug("Opened connection to RabbitMQ")
            return self.connection
        except pika.exceptions.AMQPConnectionError:
            logger.error("Cannot open connection to RabbitMQ")
            return None

    def is_connected(self) -> bool:
        """
        :return: `True` if connected, `False` otherwise
        """
        return self.connection and self.connection.is_open

    def publish(self, message: str) -> bool:
        """
        :param message:
        :return: `True` if message was published, `False` otherwise
        """
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


@cache
def get_queue_service():
    if settings.EVENTS_QUEUE_URL:
        return QueueService()
    else:
        # Mock send_event to not configured host us is not mandatory configure a queue for events
        logger.warning("MockedQueueService is used")
        return MockedQueueService()


class QueueService:
    def __init__(self):
        self._connection_pool: List[BrokerConnection] = []
        self.unsent_events: List = []

    def get_connection(self) -> BrokerConnection:
        """
        :return: A `BrokerConnection` from the connection pool if there is one available, othwerwise
            returns a new BrokerConnection
        """
        if self._connection_pool:
            return self._connection_pool.pop()
        else:
            return BrokerConnection()

    def release_connection(self, broker_connection: BrokerConnection) -> None:
        """
        Return the `BrokerConnection` to the pool

        :param broker_connection:
        :return:
        """
        return self._connection_pool.insert(0, broker_connection)

    def send_event(self, payload: Dict[str, Any]) -> int:
        """
        Publish event using the `BrokerConnection`

        :param payload: Number of events published
        """
        broker_connection = self.get_connection()

        event = json.dumps(payload)
        if broker_connection.publish(event):
            logger.debug("Event correctly sent: %s", event)
            self.release_connection(broker_connection)
            return self.send_unsent_events() + 1

        logger.warning("Event can not be sent due any connection error")
        logger.debug("Adding %s to unsent messages", payload)
        self.unsent_events.append(event)
        return 0

    def send_unsent_events(self) -> int:
        """
        If connection is ready send the unsent messages list

        :return: number of messages sent
        """
        if not self.unsent_events:
            return 0

        broker_connection = self.get_connection()

        # Avoid race conditions
        unsent_events = self.unsent_events
        self.unsent_events = []

        total_sent_events = 0
        logger.info("Sending %i not sent messages", len(unsent_events))
        for unsent_message in unsent_events:
            if broker_connection.publish(unsent_message):
                total_sent_events += 1
            else:
                self.unsent_events.append(unsent_message)

        self.release_connection(broker_connection)
        logger.info("Sent %i not sent messages", total_sent_events)
        return total_sent_events

    def clear_unsent_events(self):
        self.unsent_events.clear()


class MockedQueueService:
    """
    Mocked class to use in case that there is not rabbitMq queue to send events
    """

    def send_event(self, event: Dict[str, Any]):
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
