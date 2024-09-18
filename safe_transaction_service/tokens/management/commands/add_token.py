from django.core.management.base import BaseCommand

from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.ethereum_client import InvalidERC20Info
from safe_eth.eth.utils import fast_to_checksum_address

from ...models import Token


class Command(BaseCommand):
    help = "Update list of tokens"

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument(
            "tokens", nargs="+", help="Token/s address/es to add to the token list"
        )
        parser.add_argument(
            "--no-prompt",
            help="If set, add the tokens without prompt",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        tokens = options["tokens"]
        no_prompt = options["no_prompt"]
        ethereum_client = get_auto_ethereum_client()

        for token_address in tokens:
            token_address = fast_to_checksum_address(token_address)
            try:
                token = Token.objects.get(address=token_address)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Token {token.name} - {token.symbol} with address "
                        f"{token_address} already exists"
                    )
                )
                if not token.trusted:  # Mark token as trusted if it's not
                    token.set_trusted()
                    self.stdout.write(
                        self.style.SUCCESS(f"Marking token {token_address} as trusted")
                    )
                continue
            except Token.DoesNotExist:
                pass

            try:
                info = ethereum_client.erc20.get_info(token_address)
                decimals = info.decimals
            except InvalidERC20Info:  # Try with a ERC721
                info = ethereum_client.erc721.get_info(token_address)
                self.stdout.write(self.style.SUCCESS("Detected ERC721 token"))
                decimals = 0

            if no_prompt:
                response = "y"
            else:
                response = (
                    input(f"Do you want to create a token {info} (y/n) ")
                    .strip()
                    .lower()
                )
            if response == "y":
                Token.objects.create(
                    address=token_address,
                    name=info.name,
                    symbol=info.symbol,
                    decimals=decimals,
                    trusted=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created token {info.name} on address {token_address}"
                    )
                )
