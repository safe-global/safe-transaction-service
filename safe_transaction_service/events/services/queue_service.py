# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from functools import cache
from typing import Any

from django.conf import settings
from django.db import transaction

import orjson
from kombu import Connection, Exchange, Producer
from kombu.pools import producers

logger = logging.getLogger(__name__)


class BaseQueueService:
    """
    Common behavior for the real and the mocked queue services. Subclasses
    only implement ``send_events``.
    """

    def send_events(self, payloads: list[dict[str, Any]]) -> int:
        raise NotImplementedError

    def send_event(self, payload: dict[str, Any]) -> int:
        """
        Serialize and publish payload. On failure, buffer it.
        On success, also flush any previously buffered events.

        :return: number of events published (1 + any flushed unsent)
        """
        return self.send_events([payload])

    def send_events_on_commit(self, payloads: list[dict[str, Any]]) -> None:
        """
        Publish ``payloads`` only once the current database transaction is
        committed, so consumers can never observe an event before the data
        backing it is visible. If no transaction is open, publish immediately.
        If the transaction is rolled back, the events are discarded.

        Payloads must be built eagerly by the caller (inside the transaction)
        — only the publish is deferred. ``send_events`` never raises (failed
        events are buffered), and ``robust=True`` keeps any unexpected failure
        from preventing sibling ``on_commit`` callbacks.

        :param payloads: Event payloads to publish after commit
        """
        if not payloads:
            return
        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(lambda: self.send_events(payloads), robust=True)
        else:
            # Bypass `transaction.on_commit`: with no transaction open it runs
            # the callback immediately anyway, but its autocommit check would
            # force-open a DB connection (`get_autocommit` ->
            # `ensure_connection`) — no need to touch the database just to
            # publish
            self.send_events(payloads)


class QueueService(BaseQueueService):
    def __init__(self):
        # Topic exchange — events are published here so consumers can subscribe
        # by routing-key pattern. Routing keys are "{chainId}.{type}.{address}".
        self.exchange = Exchange(
            settings.EVENTS_QUEUE_TOPIC_EXCHANGE_NAME,
            type="topic",
            durable=True,
        )
        # Legacy fanout exchange. Existing consumers stay bound to it; we bind
        # it downstream of the topic exchange (routing_key="#") so every event
        # still reaches them while consumers migrate to topic-based bindings.
        self.legacy_exchange = Exchange(
            settings.EVENTS_QUEUE_EXCHANGE_NAME,
            type="fanout",
            durable=True,
        )
        self.connection = Connection(settings.EVENTS_QUEUE_URL)
        limit = settings.EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT
        if limit:
            producers[self.connection].limit = limit
        self.unsent_events: list[tuple[bytes, str]] = []
        self._ensure_legacy_binding()

    def _ensure_legacy_binding(self) -> None:
        """
        Declare both exchanges and bind the legacy fanout exchange as a
        destination of the topic exchange (``routing_key="#"``) so existing
        fanout consumers keep receiving every event during the migration to
        topic-based bindings.

        Called once from ``__init__``. Forces the connection to open and
        re-raises any broker error so the operator is alerted rather than
        silently dropping events for legacy consumers — the ``@cache`` on
        ``get_queue_service`` does not cache exceptions, so a subsequent
        event will retry construction.

        :raises Exception: Re-raises any broker error from declaring the
            exchanges or creating the exchange-to-exchange binding.
        """
        try:
            with self.connection.channel() as channel:
                self.exchange(channel).declare()
                self.legacy_exchange(channel).declare()
                self.legacy_exchange(channel).bind_to(
                    exchange=self.exchange, routing_key="#"
                )
        except Exception as exc:
            logger.error(
                "Could not bind legacy fanout exchange to topic exchange: %s",
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def _build_routing_key(payload: dict[str, Any]) -> str:
        """
        Build the topic-exchange routing key for an event payload.

        The key has the format ``{chainId}.{type}.{address}``, where each part
        is a single AMQP word (no ``.``). Missing parts are replaced with ``_``
        so the key always has three segments — this keeps ``*``-wildcard
        bindings (which match exactly one word) usable by consumers. The
        address segment is lower-cased so consumer bindings can ignore the
        EIP-55 checksum casing of the payload.

        :param payload: Event payload as produced by ``build_event_payload`` /
            ``build_*_delegate_payload`` / ``build_reorg_payload``.
        :return: Routing key ready to pass to ``producer.publish``.
        """
        chain_id = payload.get("chainId") or "_"
        event_type = payload.get("type") or "_"
        address = payload.get("address")
        address_part = address.lower() if address else "_"
        return f"{chain_id}.{event_type}.{address_part}"

    def _try_publish(self, producer: Producer, event: bytes, routing_key: str) -> bool:
        """
        Attempt to publish one pre-serialized JSON event with the given
        producer. Returns True on success, never raises.
        """
        try:
            producer.publish(
                event,
                exchange=self.exchange,
                declare=[self.exchange],
                routing_key=routing_key,
                content_type="application/json",
                content_encoding="utf-8",
                retry=True,
                retry_policy={"max_retries": 1, "interval_start": 0},
                serializer="raw",
            )
            logger.debug("Event sent with routing_key=%s: %s", routing_key, event)
            return True
        except Exception as exc:
            logger.warning("Failed to publish event: %s", exc)
            return False

    def _publish_events(self, events: list[tuple[bytes, str]]) -> int:
        """
        Publish pre-serialized events in order, acquiring a producer from the
        pool only once. Stops on the first failure, never raises.

        :param events: List of ``(serialized_event, routing_key)`` tuples
        :return: Number of events published
        """
        total = 0
        try:
            with producers[self.connection].acquire(block=False) as producer:
                for event, routing_key in events:
                    if not self._try_publish(producer, event, routing_key):
                        break
                    total += 1
        except Exception as exc:
            # With `block=False`, an exhausted pool raises `LimitExceeded`,
            # which is NOT an `OperationalError` — catch everything so
            # unpublished events are always buffered by the caller
            logger.warning("Could not acquire a producer from the pool: %s", exc)
        return total

    def send_events(self, payloads: list[dict[str, Any]]) -> int:
        """
        Serialize and publish several payloads, acquiring a producer from the
        pool only once. Never raises: from the first failed event on, events
        are buffered, preserving order. On full success, also flush any
        previously buffered events.

        :return: number of events published (payloads + any flushed unsent)
        """
        events: list[tuple[bytes, str]] = []
        for payload in payloads:
            try:
                events.append((orjson.dumps(payload), self._build_routing_key(payload)))
            except Exception:
                logger.error("Cannot serialize payload %s", payload, exc_info=True)
        if not events:
            return 0 + self.send_unsent_events()
        total = self._publish_events(events)
        if total != len(events):
            unsent = events[total:]
            logger.debug(
                "Adding %d events to unsent messages, routing keys: %s",
                len(unsent),
                [routing_key for _, routing_key in unsent],
            )
            self.unsent_events.extend(unsent)
            return total
        return total + self.send_unsent_events()

    def send_unsent_events(self) -> int:
        """
        Flush the unsent buffer. Stops on first failure, preserving order.

        :return: number of events published
        """
        if not self.unsent_events:
            return 0
        unsent = self.unsent_events
        self.unsent_events = []
        logger.info("Sending %d previously unsent messages", len(unsent))
        total = self._publish_events(unsent)
        if total != len(unsent):
            self.unsent_events.extend(unsent[total:])
            logger.info(
                "Sent %d / %d unsent messages before failure", total, len(unsent)
            )
        else:
            logger.info("Sent all %d unsent messages", total)
        return total

    def clear_unsent_events(self) -> None:
        self.unsent_events.clear()


class MockedQueueService(BaseQueueService):
    """Used when EVENTS_QUEUE_URL is not configured."""

    def send_events(self, payloads: list[dict[str, Any]]) -> int:
        logger.debug("MockedQueueService: Not sending %d events", len(payloads))
        return 0


@cache
def get_queue_service() -> BaseQueueService:
    if settings.EVENTS_QUEUE_URL:
        return QueueService()
    logger.warning("MockedQueueService is used")
    return MockedQueueService()
