# SPDX-License-Identifier: FSL-1.1-MIT
from django.http import HttpRequest

from safe_transaction_service.utils.request_context import (
    SAFE_REQ_ID_HEADER,
    safe_req_id_context,
)


class SafeRequestIdMiddleware:
    """
    Make the ``x-safe-req-id`` header set by the edge available to the code
    serving the request (event publishing, logs) through a context variable.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        with safe_req_id_context(request.headers.get(SAFE_REQ_ID_HEADER)):
            return self.get_response(request)
