from django.core.management.base import BaseCommand

from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.ethereum_client import InvalidERC20Info, InvalidERC721Info

from ...clients import CoinMarketCapClient
from ...models import Token


class Command(BaseCommand):
    help = "Update list of tokens"

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument("api-key", help="Coinmarketcap API Key", type=str)
        parser.add_argument(
            "--download-folder", help="Download images to folder", type=str
        )
        parser.add_argument(
            "--store-db",
            help="Do changes on database",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        api_key = options["api-key"]
        download_folder = options["download_folder"]
        store_db = options["store_db"]

        ethereum_client = get_auto_ethereum_client()
        coinmarketcap_client = CoinMarketCapClient(api_key)

        self.stdout.write(self.style.SUCCESS("Importing tokens from Coinmarketcap"))
        if not store_db:
            self.stdout.write(
                self.style.SUCCESS(
                    "Not modifying database. Set --store-db if you want so"
                )
            )

        for token in coinmarketcap_client.get_ethereum_tokens():
            if download_folder:
                coinmarketcap_client.download_file(
                    token.logo_uri, download_folder, f"{token.token_address}.png"
                )

            if not store_db:
                continue
            try:
                token_db = Token.objects.get(address=token.token_address)
                if not token_db.trusted:
                    token_db.set_trusted()
            except Token.DoesNotExist:
                try:
                    token_info = ethereum_client.erc20.get_info(token.token_address)
                    decimals = token_info.decimals
                except InvalidERC20Info:
                    try:
                        token_info = ethereum_client.erc721.get_info(
                            token.token_address
                        )
                        decimals = 0
                    except InvalidERC721Info:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Cannot get token information for {token.name} at address {token.token_address}"
                            )
                        )
                        continue

                Token.objects.create(
                    address=token.token_address,
                    name=token_info.name,
                    symbol=token.symbol,
                    decimals=decimals,
                    trusted=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Inserted new token {token_info.name} at address {token.token_address}"
                    )
                )
