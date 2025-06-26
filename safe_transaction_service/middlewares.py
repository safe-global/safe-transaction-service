import logging


class ProxyPrefixMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefix = request.META.get("HTTP_X_FORWARDED_PREFIX", "")
        logging.debug(f"HTTP_X_FORWARDED_PREFIX:{prefix}")
        if prefix:
            original_get_full_path = request.get_full_path

            def patched_get_full_path(force_append_slash=False):
                return prefix + original_get_full_path(force_append_slash)

            request.get_full_path = patched_get_full_path

        return self.get_response(request)
