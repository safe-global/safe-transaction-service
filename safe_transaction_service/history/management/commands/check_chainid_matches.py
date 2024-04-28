from django.core.management.base import BaseCommand, CommandError

from safe_transaction_service.account_abstraction.utils import get_bundler_client
from safe_transaction_service.utils.ethereum import get_chain_id

from ...models import Chain


class Command(BaseCommand):
    help = "Check current connected Ethereum RPC chainId matches the one previously configured"

    def handle(self, *args, **options):
        chain_id = get_chain_id()

        try:
            chain = Chain.objects.get()  # Only one element in the table
        except Chain.DoesNotExist:
            chain = Chain.objects.create(chain_id=chain_id)

        if chain_id != chain.chain_id:
            raise CommandError(
                f"EthereumRPC chainId {chain_id} does not match previously used chainId {chain.chain_id}"
            )
        self.stdout.write(
            self.style.SUCCESS(f"EthereumRPC chainId {chain_id} looks good")
        )

        if bundler_client := get_bundler_client():
            bundler_chain_id = bundler_client.get_chain_id()
            if bundler_chain_id != chain.chain_id:
                raise CommandError(
                    f"ERC4337 BundlerClient chainId {bundler_chain_id} does not match "
                    f"EthereumClient chainId {chain.chain_id}"
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"ERC4337 BundlerClient chainId {chain_id} looks good"
                )
            )
