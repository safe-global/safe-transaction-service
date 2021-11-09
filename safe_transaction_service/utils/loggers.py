import logging
import time

from django.http import HttpRequest

from gunicorn import glogging


def get_milliseconds_now():
    return int(time.time() * 1000)


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not ("GET /check/" in message and "200" in message)


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
        milliseconds = get_milliseconds_now()
        response = self.get_response(request)
        if request.resolver_match:
            route = (
                request.resolver_match.route if request.resolver_match else request.path
            )
            delta = get_milliseconds_now() - milliseconds
            self.logger.info(
                "MT::%s::%s::%s::%d::%s",
                request.method,
                route,
                delta,
                response.status_code,
                request.path,
            )
        return response
