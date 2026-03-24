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
        self.exchange = Exchange(
            settings.EVENTS_QUEUE_EXCHANGE_NAME,
            type="fanout",
            durable=True,
        )
        self.connection = Connection(settings.EVENTS_QUEUE_URL)
        limit = settings.EVENTS_QUEUE_POOL_CONNECTIONS_LIMIT
        if limit:
            producers[self.connection].limit = limit
        self.unsent_events: list[bytes] = []

    def _try_publish(self, event: bytes) -> bool:
        """Attempt to publish one pre-serialized JSON event. Returns True on success."""
        try:
            with producers[self.connection].acquire(block=False) as producer:
                producer.publish(
                    event,
                    exchange=self.exchange,
                    declare=[self.exchange],
                    content_type="application/json",
                    content_encoding="utf-8",
                    retry=True,
                    retry_policy={"max_retries": 1, "interval_start": 0},
                    serializer="raw",
                )
            logger.debug("Event sent: %s", event)
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
        if not self._try_publish(event):
            logger.debug("Adding %s to unsent messages", payload)
            self.unsent_events.append(event)
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
        for i, event in enumerate(unsent):
            if self._try_publish(event):
                total += 1
            else:
                self.unsent_events.append(event)
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
