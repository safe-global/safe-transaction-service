import json
from unittest import mock

from django.test import TestCase

from pika.channel import Channel
from pika.exceptions import ConnectionClosedByBroker

from safe_transaction_service.events.services.queue_service import (
    BrokerConnection,
    get_queue_service,
)


class TestQueueService(TestCase):
    def setUp(self):
        broker_connection = BrokerConnection()
        # Create queue for test
        self.queue = "test_queue"

        broker_connection.channel.queue_declare(self.queue)
        broker_connection.channel.queue_bind(
            self.queue, broker_connection.exchange_name
        )
        # Clean queue to avoid old messages
        broker_connection.channel.queue_purge(self.queue)

    def test_send_unsent_messages(self):
        queue_service = get_queue_service()
        # Clean previous pool connections
        queue_service._connection_pool = []
        messages_to_send = 10
        queue_service.clear_unsent_events()
        self.assertEquals(len(queue_service._connection_pool), 0)
        with mock.patch.object(
            Channel,
            "basic_publish",
            side_effect=ConnectionClosedByBroker(320, "Connection closed"),
        ):
            for i in range(messages_to_send):
                payload = f"not sent {i}"
                queue_service.send_event(payload)

            self.assertEquals(len(queue_service.unsent_events), messages_to_send)
            self.assertEquals(queue_service.send_unsent_events(), 0)

        # After reconnection should send event and previous messages (10+1)
        self.assertEquals(queue_service.send_event("not sent 11"), messages_to_send + 1)
        # Everything should be sent by send_event
        self.assertEquals(queue_service.send_unsent_events(), 0)
        self.assertEquals(len(queue_service.unsent_events), 0)
        # Just one connection should be requested
        self.assertEquals(len(queue_service._connection_pool), 1)
        broker_connection = queue_service.get_connection()
        # First event published should be the last 1
        _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
        self.assertEquals(json.loads(body), "not sent 11")
        # Check if all unsent_events were sent
        for i in range(messages_to_send):
            payload = f"not sent {i}"
            _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
            self.assertEquals(json.loads(body), payload)

    def test_send_event_to_queue(self):
        payload = {"event": "test_event", "type": "event type"}
        queue_service = get_queue_service()
        # Clean previous pool connections
        queue_service._connection_pool = []
        self.assertEquals(len(queue_service._connection_pool), 0)
        queue_service.send_event(payload)
        self.assertEquals(len(queue_service._connection_pool), 1)
        broker_connection = queue_service.get_connection()
        # Check if message was written to the queue
        _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
        self.assertEquals(json.loads(body), payload)

    def test_get_connection(self):
        queue_service = get_queue_service()
        # Clean previous pool connections
        queue_service._connection_pool = []
        self.assertEquals(len(queue_service._connection_pool), 0)
        connection_1 = queue_service.get_connection()
        self.assertEquals(len(queue_service._connection_pool), 0)
        connection_2 = queue_service.get_connection()
        self.assertEquals(len(queue_service._connection_pool), 0)
        queue_service.release_connection(connection_1)
        self.assertEquals(len(queue_service._connection_pool), 1)
        queue_service.release_connection(connection_2)
        self.assertEquals(len(queue_service._connection_pool), 2)
