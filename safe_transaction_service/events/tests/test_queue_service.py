import json
from unittest import mock

from django.test import TestCase

from pika.channel import Channel
from pika.exceptions import ConnectionClosedByBroker

from ..services.queue_service import BrokerConnection, QueueService, get_queue_service


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
        self.assertEqual(len(queue_service._connection_pool), 0)
        with mock.patch.object(
            Channel,
            "basic_publish",
            side_effect=ConnectionClosedByBroker(320, "Connection closed"),
        ):
            for i in range(messages_to_send):
                payload = f"not sent {i}"
                queue_service.send_event(payload)

            self.assertEqual(len(queue_service.unsent_events), messages_to_send)
            self.assertEqual(queue_service.send_unsent_events(), 0)

        # After reconnection should send event and previous messages (10+1)
        self.assertEqual(queue_service.send_event("not sent 11"), messages_to_send + 1)
        # Everything should be sent by send_event
        self.assertEqual(queue_service.send_unsent_events(), 0)
        self.assertEqual(len(queue_service.unsent_events), 0)
        # Just one connection should be requested
        self.assertEqual(len(queue_service._connection_pool), 1)
        broker_connection = queue_service.get_connection()
        # First event published should be the last 1
        _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
        self.assertEqual(json.loads(body), "not sent 11")
        # Check if all unsent_events were sent
        for i in range(messages_to_send):
            payload = f"not sent {i}"
            _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
            self.assertEqual(json.loads(body), payload)

    def test_send_with_pool_limit(self):
        queue_service = QueueService()
        payload = "Pool limit test"
        # Unused connection, just to reach the limit
        connection_1 = queue_service.get_connection()
        self.assertEqual(len(queue_service.unsent_events), 0)
        self.assertEqual(queue_service.send_event(payload), 1)
        with self.settings(EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT=1):
            self.assertEqual(queue_service._total_connections, 1)
            self.assertEqual(len(queue_service.unsent_events), 0)
            self.assertEqual(queue_service.send_event(payload), 0)
            self.assertEqual(len(queue_service.unsent_events), 1)
            queue_service.release_connection(connection_1)
            self.assertEqual(len(queue_service.unsent_events), 1)
            self.assertEqual(queue_service.send_event(payload), 2)
            self.assertEqual(len(queue_service.unsent_events), 0)

    def test_send_event_to_queue(self):
        payload = {"event": "test_event", "type": "event type"}
        queue_service = QueueService()
        # Clean previous connection pool
        queue_service._connection_pool = []
        self.assertEqual(len(queue_service._connection_pool), 0)
        queue_service.send_event(payload)
        self.assertEqual(len(queue_service._connection_pool), 1)
        broker_connection = queue_service.get_connection()
        # Check if message was written to the queue
        _, _, body = broker_connection.channel.basic_get(self.queue, auto_ack=True)
        self.assertEqual(json.loads(body), payload)

    def test_get_connection(self):
        queue_service = QueueService()
        # Clean previous connection pool
        queue_service._connection_pool = []
        self.assertEqual(len(queue_service._connection_pool), 0)
        self.assertEqual(queue_service._total_connections, 0)
        connection_1 = queue_service.get_connection()
        self.assertEqual(len(queue_service._connection_pool), 0)
        self.assertEqual(queue_service._total_connections, 1)
        connection_2 = queue_service.get_connection()
        self.assertEqual(len(queue_service._connection_pool), 0)
        self.assertEqual(queue_service._total_connections, 2)
        queue_service.release_connection(connection_1)
        self.assertEqual(len(queue_service._connection_pool), 1)
        self.assertEqual(queue_service._total_connections, 1)
        queue_service.release_connection(connection_2)
        self.assertEqual(len(queue_service._connection_pool), 2)
        self.assertEqual(queue_service._total_connections, 0)
        with self.settings(EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT=1):
            connection_1 = queue_service.get_connection()
            self.assertEqual(len(queue_service._connection_pool), 1)
            self.assertEqual(queue_service._total_connections, 1)
            # We should reach the connection limit of the pool
            connection_1 = queue_service.get_connection()
            self.assertEqual(len(queue_service._connection_pool), 1)
            self.assertEqual(queue_service._total_connections, 1)
            self.assertIsNone(connection_1)
