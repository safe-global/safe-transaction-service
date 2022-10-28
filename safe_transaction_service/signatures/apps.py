from django.apps import AppConfig


class ContractsConfig(AppConfig):
    name = "safe_transaction_service.signatures"
    verbose_name = "Safe Signatures app"

    def ready(self):
        from . import signals  # noqa
