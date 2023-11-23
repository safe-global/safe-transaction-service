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


class QueueServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            if settings.EVENTS_QUEUE_URL:
                if settings.EVENTS_QUEUE_ASYNC_CONNECTION:
                    cls.instance = AsyncQueueService()
                else:
                    cls.instance = SyncQueueService()
            else:
                # Mock send_event to not configured host us is not mandatory configure a queue for events
                cls.instance = MockedQueueService()
                logger.warning("MockedQueueService is used")
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


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
                self.unsent_events.append(payload)
            return False

        try:
            event = json.dumps(payload)
            self._channel.basic_publish(
                exchange=self.exchange_name, routing_key="", body=event
            )
            return True
        except pika.exceptions.ConnectionClosedByBroker:
            logger.warning("Event can not be sent due to there is no channel opened")
            if fail_retry:
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


class AsyncQueueService(QueueService):
    # Singleton class definition
    def __init__(self):
        super().__init__()
        self.connect()

    def connect(self) -> GeventConnection:
        """
        This method connects to RabbitMq.
        When the connection is established, the on_connection_open method
        will be invoked by pika.

        :return: GeventConnection
        """
        return GeventConnection(
            self._connection_parameters,
            on_open_callback=self.on_connection_open,
            on_open_error_callback=self.on_connection_open_error,
            on_close_callback=self.on_connection_closed,
        )

    def on_connection_open(self, connection: GeventConnection):
        """
        This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object.

        :param GeventConnection connection: The connection
        """

        logger.info("Connection opened with %s", self._connection_parameters.host)
        self._connection = connection
        self.open_channel()

    def on_connection_open_error(self, connection: GeventConnection, err: Exception):
        """
        This method is called by pika if the connection to RabbitMQ
        can't be established. Connection object is paased if were necessary
        Always retry the reconnection every 5 seconds.

        :param GeventConnection: The connection
        :param Exception err: The error
        """
        logger.error(
            "Connection open failed with %s, retrying in 5 seconds: %s",
            self._connection_parameters.host,
            err,
        )
        connection.ioloop.call_later(5, self.connect)

    def on_connection_closed(self, connection: GeventConnection, reason: Exception):
        """
        This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param GeventConnection: The closed connection obj
        :param Exception reason: exception representing reason for loss of
            connection.
        """
        self._channel = None
        logger.error(
            "Connection closed with %s, reopening in 5 seconds: %s",
            self._connection_parameters.host,
            reason,
        )
        connection.ioloop.call_later(5, self.connect)

    def open_channel(self):
        """
        This method will open a new channel with RabbitMQ by issuing the
        Channel.Open RPC command. When RabbitMQ confirms the channel is open
        by sending the Channel.OpenOK RPC reply, the on_channel_open method
        will be invoked.
        """
        logger.info("Opening a new channel")
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel: Channel):
        """
        This method is invoked by pika when the channel has been opened.
        The channel object is passed in so we can make use of it.

        :param pika.channel.Channel channel: The channel object
        """
        logger.info("Channel with number %i opened", channel.channel_number)
        self._channel = channel
        self._channel.add_on_close_callback(self.on_channel_closed)
        self.setup_exchange()

    def on_channel_closed(self, channel: Channel, reason: Exception):
        """
        Invoked by pika when RabbitMQ unexpectedly closes the channel.
        Channels are usually closed if you attempt to do something that
        violates the protocol.
        In this method we retry to open a new channel with rabbitMQ if the connection is still open.

        :param Channel channel: The closed channel
        :param Exception reason: why the channel was closed
        """
        logger.warning("Channel %i was closed: %s", channel.channel_number, reason)
        self._channel = None
        if self._connection and self._connection.is_open:
            # If channel was closed and connection is still active we try to reopen the channel
            logger.error(
                "Connection is opened retry to open channel in 5 seconds: %s",
                self._connection_parameters.host,
                reason,
            )
            self._connection.ioloop.call_later(5, self.open_channel())

    def setup_exchange(self):
        """
        Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC
        command. When it is complete, the on_exchange_declareok method will
        be invoked by pika.
        """
        logger.info("Declaring exchange %s", self.exchange_name)

        self._channel.exchange_declare(
            exchange=self.exchange_name,
            exchange_type=ExchangeType.fanout,
            durable=True,
            callback=self.on_exchange_declareok,
        )

    def on_exchange_declareok(self, _unused_frame):
        """Invoked by pika when RabbitMQ has finished the Exchange.Declare RPC
        command.
        Send unsent messages that cannot be sent as due connection errors.

        :param pika.Frame.Method unused_frame: Exchange.DeclareOk response frame
        """

        logger.info("Exchange declared: %s", self.exchange_name)
        self.send_unsent_events()


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
            self.setup_exchange()
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
