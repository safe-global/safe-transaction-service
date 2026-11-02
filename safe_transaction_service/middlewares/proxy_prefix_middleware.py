# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from urllib.parse import quote, unquote

from django.http import HttpRequest
from django.urls import set_script_prefix
from django.utils.http import RFC3986_SUBDELIMS


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
        # WSGI and ASGI give the header bytes as ISO-8859-1; Django paths are decoded text
        header = request.META.get("HTTP_X_FORWARDED_PREFIX", "").encode("iso-8859-1")
        prefix = unquote(header.decode(errors="replace")).rstrip("/")
        # Encode as reverse() encodes the script prefix, so its URLs get the prefix once
        uri_prefix = quote(prefix, safe=RFC3986_SUBDELIMS + "/~:@")
        self.logger.debug(f"HTTP_X_FORWARDED_PREFIX:{uri_prefix}")
        if "HTTP_X_FORWARDED_PREFIX" in request.META:
            # The schema generator and the schema cache key read the normalized value
            request.META["HTTP_X_FORWARDED_PREFIX"] = uri_prefix
        if prefix:
            request.META["SCRIPT_NAME"] = prefix
            set_script_prefix(prefix)

            original_get_full_path = request.get_full_path

            def patched_get_full_path(force_append_slash=False):
                path = original_get_full_path(force_append_slash)
                if path.startswith(uri_prefix):
                    return path
                return uri_prefix + path

            request.get_full_path = patched_get_full_path

            original_build_absolute_uri = request.build_absolute_uri

            def patched_build_absolute_uri(location=None):
                uri = original_build_absolute_uri(location)
                host_with_prefix = request.get_host() + uri_prefix
                if host_with_prefix in uri:
                    return uri
                return uri.replace(request.get_host(), host_with_prefix, 1)

            request.build_absolute_uri = patched_build_absolute_uri

        return self.get_response(request)
