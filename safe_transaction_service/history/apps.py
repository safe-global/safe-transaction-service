import sys

from django.apps import AppConfig


class HistoryConfig(AppConfig):
    name = "safe_transaction_service.history"
    verbose_name = "Safe Transaction Service"

    def ready(self):
        from . import signals  # noqa

        for argument in sys.argv:
            if "gunicorn" in argument:  # pragma: no cover
                # Just run this on production
                # TODO Find a better way
                from safe_transaction_service.contracts.tx_decoder import (
                    get_db_tx_decoder,
                )

                get_db_tx_decoder()  # Build tx decoder cache
                break
