from django.apps import AppConfig


class ContractsConfig(AppConfig):
    name = 'safe_transaction_service.contracts'
    verbose_name = 'Ethereum Contracts app'

    def ready(self):
        from . import signals  # noqa
