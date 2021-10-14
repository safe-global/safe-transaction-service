from django.core.management.base import BaseCommand

from ...models import WebHook


class Command(BaseCommand):
    help = "Binds confirmations with multisig txs"

    def add_arguments(self, parser):
        parser.add_argument("--url", help="url to send webhooks to", required=True)

    def handle(self, *args, **options):
        url = options["url"]
        WebHook.objects.get_or_create(url=url, address="")

        self.stdout.write(self.style.SUCCESS(f"Created webhook for {url}"))
