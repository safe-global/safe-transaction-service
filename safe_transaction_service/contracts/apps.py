from django.apps import AppConfig


class ContractsConfig(AppConfig):
    name = 'contracts'
    verbose_name = 'Ethereum Contracts app'

    def ready(self):
        from . import signals  # noqa
