from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from ...models import Contract


class Command(BaseCommand):
    help = 'Check nonce calculated by the indexer is the same that blockchain nonce'

    def add_arguments(self, parser):
        parser.add_argument('addresses', nargs='+', help='Contract addresses')

    def handle(self, *args, **options):
        addresses = options['addresses']

        for address in addresses:
            try:
                with transaction.atomic():
                    if contract := Contract.objects.create_from_address(address):
                        self.stdout.write(self.style.SUCCESS(
                            f'Indexed contract with address={address} name={contract.name} '
                            f'abi-present={bool(contract.contract_abi.abi)}'
                        ))
            except IntegrityError:
                self.stdout.write(self.style.WARNING(f'Contract with address={address} was already created'))
