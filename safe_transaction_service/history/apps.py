from django.apps import AppConfig


class HistoryConfig(AppConfig):
    name = 'safe_transaction_service.history'

    def ready(self):
        from . import signals  # noqa
