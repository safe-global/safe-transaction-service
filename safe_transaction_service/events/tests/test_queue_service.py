import json
from unittest import mock

from django.test import TestCase

from pika.channel import Channel
from pika.exceptions import ConnectionClosedByBroker

from safe_transaction_service.events.services.queue_service import QueueServiceProvider


class TestQueueService(TestCase):
    def setUp(self):
        self.queue_service = QueueServiceProvider()
        # Create queue for test
        self.queue = "test_queue"
        self.queue_service._channel.queue_declare(self.queue)
        self.queue_service._channel.queue_bind(
            self.queue, self.queue_service.exchange_name
        )
        # Clean queue to avoid old messages
        self.queue_service._channel.queue_purge(self.queue)

    def test_send_unsent_messages(self):
        queue_service = QueueServiceProvider()
        messages_to_send = 10
        queue_service.remove_unsent_events()
        with mock.patch.object(
            Channel,
            "basic_publish",
            side_effect=ConnectionClosedByBroker(320, "Connection closed"),
        ):
            for i in range(messages_to_send):
                payload = f"not sent {i}"
                self.assertFalse(queue_service.send_event(payload))
            # Shouldn't add this message to unsent_messages list
            self.assertFalse(queue_service.send_event(payload, fail_retry=False))

            self.assertEquals(len(queue_service.unsent_events), messages_to_send)
            self.assertEquals(queue_service.send_unsent_events(), 0)

        # After reconnection should send messages
        self.assertEquals(queue_service.send_unsent_events(), messages_to_send)
        self.assertEquals(len(queue_service.unsent_events), 0)
        for i in range(messages_to_send):
            payload = f"not sent {i}"
            _, _, body = queue_service._channel.basic_get(self.queue, auto_ack=True)
            self.assertEquals(json.loads(body), payload)

    def test_send_event_to_queue(self):
        payload = {"event": "test_event", "type": "event type"}

        self.assertTrue(self.queue_service.send_event(payload))

        # Check if message was written to the queue
        _, _, body = self.queue_service._channel.basic_get(self.queue, auto_ack=True)
        self.assertEquals(json.loads(body), payload)
