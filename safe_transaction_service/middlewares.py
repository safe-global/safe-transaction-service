import logging

from django.http import HttpRequest

from .loggers.custom_logger import (
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


class ProxyPrefixMiddleware:
    """
    Middleware that adds a prefix from the 'HTTP_X_FORWARDED_PREFIX' header
    to the request's full path.
    This helps when the app is behind a proxy that uses URL prefixes.
    It modifies the request's build_absolute_uri method to include the prefix.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("ProxyPrefixMiddleware")

    def __call__(self, request: HttpRequest):
        prefix = request.META.get("HTTP_X_FORWARDED_PREFIX", "")
        self.logger.debug(f"HTTP_X_FORWARDED_PREFIX:{prefix}")
        if prefix:
            original_build_absolute_uri = request.build_absolute_uri

            def patched_build_absolute_uri(location=None):
                uri = original_build_absolute_uri(location)
                return uri.replace(request.get_host(), request.get_host() + prefix, 1)

            request.build_absolute_uri = patched_build_absolute_uri

        return self.get_response(request)
