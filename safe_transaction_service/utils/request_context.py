# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Edge request id (APISIX or Safe Client Gateway), also used as the AMQP header
# key on events. The edge strips client-sent values, so it is passed on as is.
# Internal only: never forward it to webhooks, SSE or API responses
SAFE_REQ_ID_HEADER = "x-safe-req-id"

_SAFE_REQ_ID_PATTERN = re.compile(r"[0-9a-f]{32}")

_safe_req_id: ContextVar[str | None] = ContextVar("safe_req_id", default=None)


@contextmanager
def safe_req_id_context(value: str | None) -> Iterator[None]:
    """
    Store ``value``, or ``None`` if it is not 32
    lowercase hex characters, and restore the previous value on exit.
    """
    if value is not None and not _SAFE_REQ_ID_PATTERN.fullmatch(value):
        logger.warning("Ignoring invalid x-safe-req-id header: %r", value[:64])
        value = None
    token = _safe_req_id.set(value)
    try:
        yield
    finally:
        _safe_req_id.reset(token)


def get_safe_req_id() -> str | None:
    return _safe_req_id.get()
