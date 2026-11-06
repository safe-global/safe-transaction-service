# SPDX-License-Identifier: FSL-1.1-MIT
import re
from contextvars import ContextVar, Token

# Edge request id (APISIX or Safe Client Gateway), also used as the AMQP header
# key on events. The edge strips client-sent values, so it is passed on as is.
# Internal only: never forward it to webhooks, SSE or API responses
SAFE_REQ_ID_HEADER = "x-safe-req-id"

_SAFE_REQ_ID_PATTERN = re.compile(r"[0-9a-f]{32}")

_safe_req_id: ContextVar[str | None] = ContextVar("safe_req_id", default=None)


def set_safe_req_id(value: str | None) -> Token:
    """
    Store ``value``, or ``None`` if it is not 32 lowercase hex characters.
    """
    if value is not None and not _SAFE_REQ_ID_PATTERN.fullmatch(value):
        value = None
    return _safe_req_id.set(value)


def reset_safe_req_id(token: Token) -> None:
    _safe_req_id.reset(token)


def get_safe_req_id() -> str | None:
    return _safe_req_id.get()
