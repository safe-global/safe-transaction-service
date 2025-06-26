import logging

from django.http import HttpRequest

from safe_transaction_service.loggers.custom_logger import (
    HttpResponseLog,
    get_milliseconds_now,
    http_request_log,
)


class LoggingMiddleware:
    """
    Http Middleware to generate request and response logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("LoggingMiddleware")

    def __call__(self, request: HttpRequest):
        start_time = get_milliseconds_now()
        response = self.get_response(request)
        if request.resolver_match:
            end_time = get_milliseconds_now()
            delta = end_time - start_time
            http_request = http_request_log(request, start_time)
            content: str | None = None
            if 400 <= response.status_code < 500 and hasattr(response, "data"):
                content = str(response.data)

            http_response = HttpResponseLog(
                response.status_code, end_time, delta, content
            )
            self.logger.info(
                "Http request",
                extra={
                    "http_response": http_response,
                    "http_request": http_request,
                },
            )
        return response
