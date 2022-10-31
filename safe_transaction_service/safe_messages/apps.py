from django.apps import AppConfig


class SafeMessagesConfig(AppConfig):
    name = "safe_transaction_service.safe_messages"
    verbose_name = "Safe Messages app"

    def ready(self):
        from . import signals  # noqa
