# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from functools import cache
from typing import Any

from django.conf import settings

import orjson
from kombu import Connection, Exchange
from kombu.exceptions import OperationalError
from kombu.pools import producers

logger = logging.getLogger(__name__)


class QueueService:
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

    def _try_publish(self, event: bytes, routing_key: str) -> bool:
        """Attempt to publish one pre-serialized JSON event. Returns True on success."""
        try:
            with producers[self.connection].acquire(block=False) as producer:
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
        except OperationalError:
            logger.debug("Connection pool exhausted, buffering event")
            return False
        except Exception as exc:
            logger.warning("Failed to publish event: %s", exc)
            return False

    def send_event(self, payload: dict[str, Any]) -> int:
        """
        Serialize and publish payload. On failure, buffer it.
        On success, also flush any previously buffered events.

        :return: number of events published (1 + any flushed unsent)
        """
        event: bytes = orjson.dumps(payload)
        routing_key = self._build_routing_key(payload)
        if not self._try_publish(event, routing_key):
            logger.debug("Adding %s to unsent messages", payload)
            self.unsent_events.append((event, routing_key))
            return 0
        return 1 + self.send_unsent_events()

    def send_unsent_events(self) -> int:
        """
        Flush the unsent buffer. Stops on first failure, preserving order.

        :return: number of events published
        """
        if not self.unsent_events:
            return 0
        unsent = self.unsent_events
        self.unsent_events = []
        total = 0
        logger.info("Sending %d previously unsent messages", len(unsent))
        for i, (event, routing_key) in enumerate(unsent):
            if self._try_publish(event, routing_key):
                total += 1
            else:
                self.unsent_events.append((event, routing_key))
                self.unsent_events.extend(unsent[i + 1 :])
                logger.info(
                    "Sent %d / %d unsent messages before failure", total, len(unsent)
                )
                return total
        logger.info("Sent all %d unsent messages", total)
        return total

    def clear_unsent_events(self) -> None:
        self.unsent_events.clear()


class MockedQueueService:
    """Used when EVENTS_QUEUE_URL is not configured."""

    def send_event(self, event: dict[str, Any]) -> int:
        logger.debug("MockedQueueService: Not sending event with payload %s", event)
        return 0


@cache
def get_queue_service():
    if settings.EVENTS_QUEUE_URL:
        return QueueService()
    logger.warning("MockedQueueService is used")
    return MockedQueueService()
