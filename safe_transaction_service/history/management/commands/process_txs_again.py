from django.core.management.base import BaseCommand

from ...models import MultisigConfirmation, MultisigTransaction, SafeStatus, InternalTxDecoded


class Command(BaseCommand):
    help = 'Delete processed entities and process traces again'

    def add_arguments(self, parser):
        # Positional arguments
        # parser.add_argument('--deployer-key', help='Private key for deployer')
        pass

    def handle(self, *args, **options):
        SafeStatus.objects.all().delete()
        MultisigConfirmation.objects.all().delete()
        MultisigTransaction.objects.all().delete()  # TODO Remove this, just for testing
        InternalTxDecoded.objects.update(processed=False)
        self.stdout.write(self.style.SUCCESS(f'All prepared to process again'))
