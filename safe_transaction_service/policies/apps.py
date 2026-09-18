# SPDX-License-Identifier: FSL-1.1-MIT
from django.apps import AppConfig


class PoliciesConfig(AppConfig):
    name = "safe_transaction_service.policies"
    verbose_name = "Safe Policy Guard indexing support"

    def ready(self):
        from . import signals  # noqa F401
