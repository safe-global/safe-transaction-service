import sys

from django.apps import AppConfig


class HistoryConfig(AppConfig):
    name = 'safe_transaction_service.history'
    verbose_name = 'Safe Transaction Service'

    def ready(self):
        from . import signals  # noqa

        if bool({'manage.py', 'shell'} - set(sys.argv)):
            # Ignore init if running from django shell
            from .indexers.tx_decoder import get_db_tx_decoder
            get_db_tx_decoder()  # Build tx decoder cache
