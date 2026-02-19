# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from functools import cache
from typing import Any

from django.conf import settings

import orjson
import pika.exceptions
from pika import BlockingConnection, URLParameters
from pika.channel import Channel
from pika.exchange_type import ExchangeType

logger = logging.getLogger(__name__)


class BrokerConnection:
    def __init__(self):
        self.exchange_name: str = settings.EVENTS_QUEUE_EXCHANGE_NAME
        self.channel: Channel | None = None
        self.connection_parameters = URLParameters(settings.EVENTS_QUEUE_URL)
        self.connection: BlockingConnection | None = self.connect()

    def connect(self) -> BlockingConnection | None:
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
            self.connection = None
            self.channel = None
            return None

    def close(self) -> None:
        """Close the underlying connection and release resources."""
        if self.connection is None:
            return
        try:
            self.connection.close()
        except pika.exceptions.AMQPError as e:
            logger.warning("Error closing RabbitMQ connection: %s", e)
        finally:
            self.connection = None
            self.channel = None

    def publish(self, message: str, retry: bool | None = True) -> bool:
        """
        :param message:
        :param retry:
        :return: `True` if message was published, `False` otherwise
        """
        if not self.channel:
            if retry:
                logger.info("The connection has been terminated, trying again.")
                self.connect()
                return self.publish(message, retry=False)
            return False
        try:
            self.channel.basic_publish(
                exchange=self.exchange_name, routing_key="", body=message
            )
            return True
        except pika.exceptions.AMQPError:
            if retry:
                logger.info("The connection has been terminated, trying again.")
                self.connect()
                return self.publish(message, retry=False)
            return False


@cache
def get_queue_service():
    if settings.EVENTS_QUEUE_URL:
        return QueueService()
    else:
        # It's not mandatory to configure a queue, so send_event will be mocked
        logger.warning("MockedQueueService is used")
        return MockedQueueService()


class QueueService:
    def __init__(self):
        self._connection_pool: list[BrokerConnection] = []
        self._total_connections: int = 0
        self.unsent_events: list[str] = []

    def get_connection(self) -> BrokerConnection | None:
        """
        :return: A `BrokerConnection` from the connection pool if there is one available, otherwise
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

        if broker_connection.channel:
            self._total_connections += 1
            return broker_connection

        logger.warning("RabbitMQ channel is not available")
        return None

    def release_connection(self, broker_connection: BrokerConnection | None) -> None:
        """
        Return the `BrokerConnection` to the pool, or discard it if None.
        When broker_connection is None, the counter is still decremented (caller
        is discarding a broken connection that was previously obtained).
        """
        self._total_connections = max(0, self._total_connections - 1)
        if broker_connection:
            self._connection_pool.insert(0, broker_connection)

    def send_event(self, payload: dict[str, Any]) -> int:
        """
        Publish event using the `BrokerConnection`.

        :param payload: Event payload to publish.
        :return: Number of events published (1 + any previously unsent now sent).
        """

        event: str = orjson.dumps(payload).decode("utf-8")
        if not (broker_connection := self.get_connection()):
            # No available connections in the pool, store event to send it later
            self.unsent_events.append(event)
            return 0

        if broker_connection.publish(event):
            logger.debug("Event correctly sent: %s", event)
            return self.send_unsent_events(broker_connection) + 1

        logger.warning("Unable to send the event due to a connection error")
        logger.debug("Adding %s to unsent messages", payload)
        self.unsent_events.append(event)
        broker_connection.close()
        self.release_connection(None)
        return 0

    def send_unsent_events(
        self, broker_connection: BrokerConnection | None = None
    ) -> int:
        """
        Send the unsent messages list. Uses the given connection if provided,
        otherwise obtains one from the pool.

        :param broker_connection: Optional connection to reuse (e.g. from send_event).
        :return: number of messages sent
        """
        if not self.unsent_events:
            if broker_connection:
                self.release_connection(broker_connection)
            return 0

        if broker_connection is None and not (
            broker_connection := self.get_connection()
        ):
            return 0

        unsent_events = self.unsent_events
        self.unsent_events = []

        total_sent_events = 0
        logger.info("Sending previously unsent messages: %i", len(unsent_events))
        for unsent_message in unsent_events:
            if broker_connection.publish(unsent_message):
                total_sent_events += 1
            else:
                # Connection likely broken; put failed message and rest back, then stop
                self.unsent_events.append(unsent_message)
                self.unsent_events.extend(unsent_events[total_sent_events + 1 :])
                broker_connection.close()
                self.release_connection(None)
                logger.info("Correctly sent messages: %i", total_sent_events)
                return total_sent_events

        self.release_connection(broker_connection)
        logger.info("Correctly sent messages: %i", total_sent_events)
        return total_sent_events

    def clear_unsent_events(self):
        self.unsent_events.clear()


class MockedQueueService:
    """
    Mocked class to use in case that there is not rabbitMq queue to send events
    """

    def send_event(self, event: dict[str, Any]) -> int:
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
        return 0
