from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

import requests
from requests import RequestException
from safe_eth.eth import get_auto_ethereum_client

from safe_transaction_service import __version__


class Command(BaseCommand):
    help = "Send slack notification"

    def handle(self, *args, **options):
        ethereum_client = get_auto_ethereum_client()
        app_name = apps.get_app_config("history").verbose_name
        network_name = ethereum_client.get_network().name.capitalize()
        startup_message = f"Starting {app_name} version {__version__} on {network_name}"
        self.stdout.write(self.style.SUCCESS(startup_message))

        if settings.SLACK_API_WEBHOOK:
            try:
                r = requests.post(
                    settings.SLACK_API_WEBHOOK,
                    json={"text": startup_message},
                    timeout=5,
                )
                if r.ok:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Slack configured, "{startup_message}" sent'
                        )
                    )
                else:
                    raise RequestException()
            except RequestException as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Cannot send slack notification to webhook "
                        f'({settings.SLACK_API_WEBHOOK}): "{e}"'
                    )
                )
        else:
            self.stdout.write(self.style.SUCCESS("Slack not configured, ignoring"))
