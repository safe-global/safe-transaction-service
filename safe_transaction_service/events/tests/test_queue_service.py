# SPDX-License-Identifier: FSL-1.1-MIT
import json
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from kombu import Connection, Exchange, Queue
from kombu.exceptions import LimitExceeded

from ..services import queue_service as queue_service_module
from ..services.queue_service import (
    EVENTS_APP_ID,
    LegacyExchange,
    QueueService,
    close_queue_service,
    get_queue_service,
)


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

    def test_send_event_sets_app_id(self):
        queue_service = QueueService()
        queue_service.send_event({"event": "test_event", "type": "event type"})
        with self.conn.channel() as channel:
            msg = self.test_queue(channel).get(no_ack=True)
        self.assertIsNotNone(msg)
        self.assertEqual(EVENTS_APP_ID, "safe-transaction-service")
        self.assertEqual(msg.properties["app_id"], EVENTS_APP_ID)

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

    def test_publish_failure_buffers_event(self):
        queue_service = QueueService()
        payload = {"message": "publish failure test"}

        with mock.patch.object(QueueService, "_try_publish", return_value=False):
            result = queue_service.send_event(payload)
            self.assertEqual(result, 0)
            self.assertEqual(len(queue_service.unsent_events), 1)

        # Next successful send flushes the buffer too
        result = queue_service.send_event({"message": "recovered"})
        self.assertEqual(result, 2)
        self.assertEqual(len(queue_service.unsent_events), 0)

    def test_send_events_to_queue(self):
        payloads = [
            {"event": f"test_event {i}", "type": "event type"} for i in range(3)
        ]
        queue_service = QueueService()
        self.assertIsNone(self._get_message())
        self.assertEqual(queue_service.send_events(payloads), 3)
        for payload in payloads:
            self.assertEqual(self._get_message(), payload)

    def test_send_events_empty_list(self):
        queue_service = QueueService()
        self.assertEqual(queue_service.send_events([]), 0)
        self.assertIsNone(self._get_message())

    def test_send_events_buffers_remaining_on_failure(self):
        queue_service = QueueService()
        queue_service.clear_unsent_events()
        payloads = [{"message": f"event {i}"} for i in range(3)]

        # First event publishes, second fails: it and the remaining one must be
        # buffered, preserving order
        with mock.patch.object(QueueService, "_try_publish", side_effect=[True, False]):
            self.assertEqual(queue_service.send_events(payloads), 1)
        self.assertEqual(len(queue_service.unsent_events), 2)

        # Next successful batch flushes the buffer too
        self.assertEqual(queue_service.send_events([{"message": "recovered"}]), 3)
        self.assertEqual(len(queue_service.unsent_events), 0)
        self.assertEqual(self._get_message(), {"message": "recovered"})
        self.assertEqual(self._get_message(), {"message": "event 1"})
        self.assertEqual(self._get_message(), {"message": "event 2"})

    def test_send_events_buffers_on_pool_exhausted(self):
        # `acquire(block=False)` raises `LimitExceeded` (not `OperationalError`)
        # when the producer pool is exhausted; events must be buffered, not
        # raise and get lost
        queue_service = QueueService()
        queue_service.clear_unsent_events()

        with mock.patch.object(
            queue_service.producer_pool, "acquire", side_effect=LimitExceeded
        ):
            self.assertEqual(queue_service.send_events([{"message": "buffered"}]), 0)
        self.assertEqual(len(queue_service.unsent_events), 1)

        # Flushed by the next successful send
        self.assertEqual(queue_service.send_event({"message": "recovered"}), 2)
        self.assertEqual(self._get_message(), {"message": "recovered"})
        self.assertEqual(self._get_message(), {"message": "buffered"})

    def test_send_events_skips_unserializable_payload(self):
        # One bad payload must not prevent its siblings from being published
        queue_service = QueueService()
        good_payload = {"message": "good"}

        with self.assertLogs(level="ERROR"):
            self.assertEqual(
                queue_service.send_events([{"message": b"\xff"}, good_payload]), 1
            )
        self.assertEqual(self._get_message(), good_payload)
        self.assertEqual(len(queue_service.unsent_events), 0)

    def test_send_events_on_commit(self):
        payloads = [{"message": "sent on commit"}]
        queue_service = QueueService()
        with mock.patch.object(QueueService, "send_events") as send_events_mock:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                queue_service.send_events_on_commit(payloads)
                # Nothing is published while the transaction is open
                send_events_mock.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            send_events_mock.assert_called_once_with(payloads)

    def test_send_events_on_commit_empty_list(self):
        # No callback is registered when there is nothing to send
        queue_service = QueueService()
        with self.captureOnCommitCallbacks() as callbacks:
            queue_service.send_events_on_commit([])
        self.assertEqual(callbacks, [])

    def _make_queue_service(self) -> QueueService:
        queue_service = QueueService()
        self.addCleanup(queue_service.close)
        return queue_service

    def _spy_bind_to(self):
        return mock.patch.object(
            LegacyExchange, "bind_to", autospec=True, side_effect=Exchange.bind_to
        )

    def test_init_does_not_open_connections(self):
        self.assertEqual(self._make_queue_service()._open_connections(), [])

    def test_exchanges_restored_after_broker_loses_them(self):
        queue_service = self._make_queue_service()
        queue_service.send_event({"message": "before"})
        self.assertEqual(self._get_message(), {"message": "before"})

        # Broker restart: exchanges, bindings and sockets are lost
        with self.conn.channel() as channel:
            Exchange(settings.EVENTS_QUEUE_TOPIC_EXCHANGE_NAME)(channel).delete()
            Exchange(settings.EVENTS_QUEUE_EXCHANGE_NAME)(channel).delete()
        for conn in queue_service._open_connections():
            conn.collect()
        with self.conn.channel() as channel:
            self.test_queue(channel).declare()

        self.assertEqual(queue_service.send_event({"message": "after"}), 1)
        self.assertEqual(self._get_message(), {"message": "after"})

    def test_legacy_binding_declared_once_per_connection(self):
        queue_service = self._make_queue_service()
        with self._spy_bind_to() as bind_to_mock:
            queue_service.send_event({"message": "1"})
            queue_service.send_event({"message": "2"})
        bind_to_mock.assert_called_once()

    def test_bind_failure_still_publishes_and_retries(self):
        queue_service = self._make_queue_service()
        with mock.patch.object(LegacyExchange, "bind_to", side_effect=OSError):
            with self.assertLogs(queue_service_module.logger, level="ERROR"):
                self.assertEqual(queue_service.send_event({"message": "1"}), 1)
        self.assertEqual(queue_service.unsent_events, [])

        with self._spy_bind_to() as bind_to_mock:
            self.assertEqual(queue_service.send_event({"message": "2"}), 1)
        bind_to_mock.assert_called_once()

    @override_settings(EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT=2)
    def test_pool_limit_applies_to_connections_and_producers(self):
        queue_service = self._make_queue_service()
        self.assertEqual(queue_service.connection_pool.limit, 2)
        self.assertEqual(queue_service.producer_pool.limit, 2)

        producer_1 = queue_service.producer_pool.acquire(block=False)
        producer_2 = queue_service.producer_pool.acquire(block=False)
        with self.assertRaises(LimitExceeded):
            queue_service.producer_pool.acquire(block=False)
        producer_1.release()
        producer_2.release()
        self.assertEqual(len(queue_service._open_connections()), 2)

    def test_connection_name(self):
        queue_service = self._make_queue_service()
        queue_service.send_event({"message": "named"})
        (conn,) = queue_service._open_connections()
        connection_name = conn.connection.client_properties["connection_name"]
        self.assertTrue(connection_name.startswith(f"{EVENTS_APP_ID}@"))

    def test_close(self):
        queue_service = QueueService()
        with mock.patch.object(QueueService, "_try_publish", return_value=False):
            queue_service.send_event({"message": "buffered"})
        (conn,) = queue_service._open_connections()
        self.assertTrue(conn.connected)

        queue_service.close()
        self.assertFalse(conn.connected)
        self.assertEqual(queue_service.unsent_events, [])
        self.assertEqual(self._get_message(), {"message": "buffered"})

        queue_service.close()
        self.assertEqual(queue_service.send_event({"message": "2"}), 0)
        with self.assertLogs(queue_service_module.logger, level="WARNING") as logs:
            queue_service.close()
        self.assertIn("Dropping 1 unsent events", logs.output[-1])


class TestCloseQueueService(SimpleTestCase):
    def setUp(self):
        get_queue_service.cache_clear()
        self.addCleanup(get_queue_service.cache_clear)

    def test_close_queue_service_does_not_build_one(self):
        with mock.patch.object(QueueService, "close") as close_mock:
            close_queue_service()
            self.assertEqual(get_queue_service.cache_info().currsize, 0)
            close_mock.assert_not_called()

            get_queue_service()
            close_queue_service()
            close_mock.assert_called_once_with()


class TestBuildRoutingKey(SimpleTestCase):
    """
    The routing key is the contract consumers bind their queues against,
    so its shape must stay stable. These tests pin the format.
    """

    def test_full_payload_renders_chainid_type_address(self):
        payload = {
            "chainId": "1",
            "type": "EXECUTED_MULTISIG_TRANSACTION",
            "address": "0x1234567890abcdef1234567890abcdef12345678",
        }
        self.assertEqual(
            QueueService._build_routing_key(payload),
            "1.EXECUTED_MULTISIG_TRANSACTION."
            "0x1234567890abcdef1234567890abcdef12345678",
        )

    def test_address_is_lowercased_for_case_insensitive_bindings(self):
        # Payloads can carry EIP-55 checksum-cased addresses, but consumers
        # bind with a fixed casing — lowercase the address segment so the
        # routing key is stable regardless of how the payload was built.
        key = QueueService._build_routing_key(
            {
                "chainId": "1",
                "type": "MODULE_TRANSACTION",
                "address": "0xABCDef0000000000000000000000000000000000",
            }
        )
        self.assertEqual(
            key,
            "1.MODULE_TRANSACTION.0xabcdef0000000000000000000000000000000000",
        )

    def test_missing_address_uses_placeholder_to_preserve_three_segments(self):
        # A topic-exchange `*` matches exactly one word. If we emitted
        # "1.REORG_DETECTED." (trailing empty segment), bindings like
        # "*.*.0x..." would no longer match anything. The "_" placeholder
        # keeps the segment count at 3 so wildcard bindings work uniformly.
        self.assertEqual(
            QueueService._build_routing_key({"chainId": "1", "type": "REORG_DETECTED"}),
            "1.REORG_DETECTED._",
        )

    def test_none_address_is_treated_as_missing(self):
        # SafeContractDelegate without a safe_contract_id produces a payload
        # with address=None; it must not blow up or end up as "none" in the
        # routing key.
        self.assertEqual(
            QueueService._build_routing_key(
                {"chainId": "1", "type": "NEW_DELEGATE", "address": None}
            ),
            "1.NEW_DELEGATE._",
        )

    def test_empty_payload_returns_all_placeholders(self):
        # Defensive: an unexpected/empty payload must still produce a valid
        # 3-segment routing key so the publish call does not crash.
        self.assertEqual(QueueService._build_routing_key({}), "_._._")
