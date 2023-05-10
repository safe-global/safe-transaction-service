from django.core.management.base import BaseCommand, CommandError

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

        if chain.chain_id == chain_id:
            self.stdout.write(
                self.style.SUCCESS(f"EthereumRPC chainId {chain_id} looks good")
            )
        else:
            raise CommandError(
                f"EthereumRPC chainId {chain_id} does not match previously used chainId {chain.chain_id}"
            )
