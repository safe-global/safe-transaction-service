import logging

from django.http import HttpRequest


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
            # Set SCRIPT_NAME so Django generates all URLs with the prefix
            request.META["SCRIPT_NAME"] = prefix
            # Remove prefix from path_info so Django can match URL patterns
            if request.path_info.startswith(prefix):
                request.path_info = request.path_info[len(prefix) :]

            original_build_absolute_uri = request.build_absolute_uri

            def patched_build_absolute_uri(location=None):
                uri = original_build_absolute_uri(location)
                return uri.replace(request.get_host(), request.get_host() + prefix, 1)

            request.build_absolute_uri = patched_build_absolute_uri

        return self.get_response(request)
