from django.apps import AppConfig
from django.conf import settings

from safe_transaction_service.utils.redis import remove_cache_view_response


class HistoryConfig(AppConfig):
    name = "safe_transaction_service.history"
    verbose_name = "Safe Transaction Service"

    def ready(self):
        from . import signals  # noqa

        # Clean swagger cache
        remove_cache_view_response(settings.SWAGGER_CACHE_KEY)
