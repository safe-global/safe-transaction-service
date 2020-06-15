from django.core.management.base import BaseCommand

from ...clients import SafeRelayTokenClient
from ...models import Token


class Command(BaseCommand):
    help = 'Update list of tokens'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--base-url', help='Relay base url', type=str)
        parser.add_argument('--store-db', help='Do changes on database', action='store_true', default=False)

    def handle(self, *args, **options):
        base_url = options['base_url']
        store_db = options['store_db']

        self.stdout.write(self.style.SUCCESS('Importing tokens from Safe Relay'))
        if not store_db:
            self.stdout.write(self.style.SUCCESS('Not modifying database. Set --store-db if you want so'))

        if base_url:
            safe_relay_token_client = SafeRelayTokenClient(base_url)
        else:
            safe_relay_token_client = SafeRelayTokenClient()

        for token in safe_relay_token_client.get_tokens():
            self.stdout.write(self.style.SUCCESS(
                f'Got token {token.name} at address {token.address}'))
            if not store_db:
                continue

            try:
                token_db = Token.objects.get(address=token.address)
                if not token_db.trusted:
                    self.stdout.write(self.style.SUCCESS(
                        f'Trusting in token {token.name} at address {token.address}'))
                    token_db.set_trusted()
            except Token.DoesNotExist:
                Token.objects.create(
                    address=token.address,
                    name=token.name,
                    symbol=token.symbol,
                    decimals=token.decimals,
                    trusted=True,
                )
                self.stdout.write(self.style.SUCCESS(
                    f'Inserted token {token.name} at address {token.address}'))
