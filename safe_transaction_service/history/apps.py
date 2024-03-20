from django.apps import AppConfig


class HistoryConfig(AppConfig):
    name = "safe_transaction_service.history"
    verbose_name = "Safe Transaction Service"

    def ready(self):
        from . import signals  # noqa
