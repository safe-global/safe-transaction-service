import json
import logging
import time

from django.http import HttpRequest

from gunicorn import glogging

from safe_transaction_service.loggers.custom_logger import (
    HttpResponseLog,
    http_request_log,
)


def get_milliseconds_now():
    return int(time.time() * 1000)


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not ("GET /check/" in message and "200" in message)


class IgnoreSucceededNone(logging.Filter):
    """
    Ignore Celery messages like:
    ```
        Task safe_transaction_service.history.tasks.index_internal_txs_task[89ad3c46-aeb3-48a1-bd6f-2f3684323ca8]
        succeeded in 1.0970600529108196s: None
    ```
    They are usually emitted when a redis lock is active
    """

    def filter(self, rec: logging.LogRecord):
        message = rec.getMessage()
        return not ("Task" in message and "succeeded" in message and "None" in message)


class CustomGunicornLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        logger = logging.getLogger("gunicorn.access")
        logger.addFilter(IgnoreCheckUrl())


class LoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("LoggingMiddleware")

    def __call__(self, request: HttpRequest):
        start_time = get_milliseconds_now()
        response = self.get_response(request)
        if request.resolver_match:
            route = (
                request.resolver_match.route if request.resolver_match else request.path
            )
            end_time = get_milliseconds_now()
            delta = end_time - start_time
            http_request = http_request_log(request, start_time)
            content: str | None = None
            if 400 <= response.status_code < 500:
                content = json.loads(response.content.decode("utf-8"))

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
