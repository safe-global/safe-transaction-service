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
            logger.debug("Opened connection to RabbitMQ")
            return self.connection
        except pika.exceptions.AMQPError:
            logger.error("Cannot open connection to RabbitMQ")
            return None

    def publish(self, message: str, retry: Optional[bool] = True) -> bool:
        """
        :param message:
        :param retry:
        :return: `True` if message was published, `False` otherwise
        """
        try:
            self.channel.basic_publish(
                exchange=self.exchange_name, routing_key="", body=message
            )
            return True
        except pika.exceptions.AMQPError:
            if retry:
                logger.info("The connection has been terminated, trying again.")
                # One more chance
                self.connect()
                return self.publish(message, retry=False)
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
        self._total_connections: int = 0
        self.unsent_events: List = []

    def get_connection(self) -> Optional[BrokerConnection]:
        """
        :return: A `BrokerConnection` from the connection pool if there is one available, othwerwise
            returns a new BrokerConnection
        """
        if (
            settings.EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT
            and self._total_connections >= settings.EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT
        ):
            logger.warning(
                "Number of active connections reached the pool limit: %d",
                self._total_connections,
            )
            return None

        if self._connection_pool:
            broker_connection = self._connection_pool.pop()
        else:
            broker_connection = BrokerConnection()

        self._total_connections += 1
        return broker_connection

    def release_connection(self, broker_connection: Optional[BrokerConnection]):
        """
        Return the `BrokerConnection` to the pool

        :param broker_connection:
        :return:
        """
        self._total_connections -= 1
        # Don't add broken connections to the pool
        if broker_connection:
            self._connection_pool.insert(0, broker_connection)

    def send_event(self, payload: Dict[str, Any]) -> int:
        """
        Publish event using the `BrokerConnection`

        :param payload: Number of events published
        """
        event = json.dumps(payload)
        if not (broker_connection := self.get_connection()):
            # No available connections in the pool, store event to send it later
            self.unsent_events.append(event)
            return 0

        if broker_connection.publish(event):
            logger.debug("Event correctly sent: %s", event)
            self.release_connection(broker_connection)
            return self.send_unsent_events() + 1

        logger.warning("Unable to send the event due to a connection error")
        logger.debug("Adding %s to unsent messages", payload)
        self.unsent_events.append(event)
        # As the message cannot be sent, we don't want to send the problematic connection back to the pool, only reduce the number of total connections
        self.release_connection(None)
        return 0

    def send_unsent_events(self) -> int:
        """
        If connection is ready send the unsent messages list

        :return: number of messages sent
        """
        if not self.unsent_events:
            return 0

        if not (broker_connection := self.get_connection()):
            # Connection not available in the pool
            return 0

        # Avoid race conditions
        unsent_events = self.unsent_events
        self.unsent_events = []

        total_sent_events = 0
        logger.info("Sending previously unsent messages: %i", len(unsent_events))
        for unsent_message in unsent_events:
            if broker_connection.publish(unsent_message):
                total_sent_events += 1
            else:
                self.unsent_events.append(unsent_message)

        self.release_connection(broker_connection)
        logger.info("Correctly sent messages: %i", total_sent_events)
        return total_sent_events

    def clear_unsent_events(self):
        self.unsent_events.clear()


class MockedQueueService:
    """
    Mocked class to use in case that there is not rabbitMq queue to send events
    """

    def send_event(self, event: Dict[str, Any]):
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
