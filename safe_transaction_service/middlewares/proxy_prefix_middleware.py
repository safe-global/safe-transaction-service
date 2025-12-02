import logging

from django.http import HttpRequest
from django.urls import set_script_prefix


class ProxyPrefixMiddleware:
    """
    Middleware that adds a prefix from the 'HTTP_X_FORWARDED_PREFIX' header
    to the request's full path.
    This helps when the app is behind a proxy that uses URL prefixes.
    It modifies the request's build_absolute_uri and get_full_path methods to include the prefix.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("ProxyPrefixMiddleware")

    def __call__(self, request: HttpRequest):
        prefix = request.META.get("HTTP_X_FORWARDED_PREFIX", "")
        self.logger.debug(f"HTTP_X_FORWARDED_PREFIX:{prefix}")
        if prefix:
            request.META["SCRIPT_NAME"] = prefix
            set_script_prefix(prefix)

            original_get_full_path = request.get_full_path

            def patched_get_full_path(force_append_slash=False):
                path = original_get_full_path(force_append_slash)
                if path.startswith(prefix):
                    return path
                return prefix + path

            request.get_full_path = patched_get_full_path

            original_build_absolute_uri = request.build_absolute_uri

            def patched_build_absolute_uri(location=None):
                uri = original_build_absolute_uri(location)
                host_with_prefix = request.get_host() + prefix
                if host_with_prefix in uri:
                    return uri
                return uri.replace(request.get_host(), host_with_prefix, 1)

            request.build_absolute_uri = patched_build_absolute_uri

        return self.get_response(request)
