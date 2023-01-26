from django.core.management.base import BaseCommand, CommandError

from safe_transaction_service.utils.ethereum import get_ethereum_network

from ...models import Chain


class Command(BaseCommand):
    help = "Check current connected Ethereum RPC chainId matches the one previously configured"

    def handle(self, *args, **options):
        ethereum_network = get_ethereum_network()

        try:
            chain = Chain.objects.get()  # Only one element in the table
        except Chain.DoesNotExist:
            chain = Chain.objects.create(chain_id=ethereum_network.value)

        if chain.chain_id == ethereum_network.value:
            self.stdout.write(
                self.style.SUCCESS(
                    f"EthereumRPC chainId {ethereum_network.value} looks good"
                )
            )
        else:
            raise CommandError(
                f"EthereumRPC chainId {ethereum_network.value} does not match previously used chainId {chain.chain_id}"
            )
