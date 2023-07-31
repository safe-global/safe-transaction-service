import json
from unittest import mock

from django.test import TestCase

from pika.channel import Channel
from pika.exceptions import ConnectionClosedByBroker

from safe_transaction_service.events.tasks import send_event_to_queue_task
from safe_transaction_service.events.tests.test_queue_service import TestQueueService


class TestTasks(TestQueueService, TestCase):
    def test_send_event_to_queue_task(self):
        self.assertFalse(send_event_to_queue_task(None))
        payload = {"event": "test_event_task", "type": "event task type"}
        with mock.patch.object(
            Channel, "basic_publish", return_value=None
        ) as mock_publish:
            self.assertTrue(send_event_to_queue_task(payload))
            mock_publish.assert_called_once_with(
                exchange=self.queue_service.exchange_name,
                routing_key="",
                body=json.dumps(payload),
                properties=None,
                mandatory=False,
            )

        self.assertTrue(send_event_to_queue_task(payload))
        _, _, body = self.queue_service._channel.basic_get(self.queue, auto_ack=True)
        self.assertEquals(json.loads(body), payload)

        with mock.patch.object(
            Channel,
            "basic_publish",
            side_effect=ConnectionClosedByBroker(320, "Connection closed"),
        ):
            self.assertFalse(send_event_to_queue_task(payload))
