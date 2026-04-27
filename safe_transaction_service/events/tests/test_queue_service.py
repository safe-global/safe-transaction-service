# SPDX-License-Identifier: FSL-1.1-MIT
import json
from unittest import mock

from django.conf import settings
from django.test import TestCase

from kombu import Connection, Exchange, Queue

from ..services.queue_service import QueueService


class TestQueueService(TestCase):
    def setUp(self):
        self.conn = Connection(settings.EVENTS_QUEUE_URL)
        exchange = Exchange(
            settings.EVENTS_QUEUE_EXCHANGE_NAME, type="fanout", durable=True
        )
        # exclusive=True: RabbitMQ 4.x deprecated non-durable non-exclusive queues
        # (transient_nonexcl_queues). Exclusive queues are still allowed, are
        # auto-deleted when the connection closes, and still receive messages
        # routed from the fanout exchange by the broker.
        self.test_queue = Queue("test_queue", exchange=exchange, exclusive=True)
        with self.conn.channel() as channel:
            bound = self.test_queue(channel)
            bound.declare()
            bound.purge()

    def tearDown(self):
        self.conn.close()

    def _get_message(self):
        with self.conn.channel() as channel:
            msg = self.test_queue(channel).get(no_ack=True)
            if msg:
                return json.loads(msg.body)
        return None

    def test_send_event_to_queue(self):
        payload = {"event": "test_event", "type": "event type"}
        queue_service = QueueService()
        self.assertIsNone(self._get_message())
        queue_service.send_event(payload)
        self.assertEqual(self._get_message(), payload)

    def test_send_unsent_messages(self):
        queue_service = QueueService()
        messages_to_send = 10
        queue_service.clear_unsent_events()

        with mock.patch.object(QueueService, "_try_publish", return_value=False):
            for i in range(messages_to_send):
                queue_service.send_event({"message": f"not sent {i}"})
            self.assertEqual(len(queue_service.unsent_events), messages_to_send)
            self.assertEqual(queue_service.send_unsent_events(), 0)

        # After reconnection: send event + flush previously buffered (10 + 1)
        self.assertEqual(
            queue_service.send_event({"message": "not sent 11"}), messages_to_send + 1
        )
        self.assertEqual(len(queue_service.unsent_events), 0)
        self.assertEqual(queue_service.send_unsent_events(), 0)

        # Main event published first, buffered events flushed in order after
        self.assertEqual(self._get_message(), {"message": "not sent 11"})
        for i in range(messages_to_send):
            self.assertEqual(self._get_message(), {"message": f"not sent {i}"})

    def test_pool_exhausted_buffers_event(self):
        queue_service = QueueService()
        payload = {"message": "pool exhausted test"}

        with mock.patch.object(QueueService, "_try_publish", return_value=False):
            result = queue_service.send_event(payload)
            self.assertEqual(result, 0)
            self.assertEqual(len(queue_service.unsent_events), 1)

        # Next successful send flushes the buffer too
        result = queue_service.send_event({"message": "recovered"})
        self.assertEqual(result, 2)
        self.assertEqual(len(queue_service.unsent_events), 0)
