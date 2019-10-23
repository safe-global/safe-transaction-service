from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import ProxyFactory, SafeMasterCopy


class Command(BaseCommand):
    help = 'Setup Transaction Service For Mainnet'

    def handle(self, *args, **options):
        call_command('setup_service')
        SafeMasterCopy.objects.get_or_create(address='0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                                             defaults={
                                                 'initial_block_number': 7457553,
                                                 'tx_block_number': 7457553,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0x8942595A2dC5181Df0465AF0D7be08c8f23C93af',
                                             defaults={
                                                 'initial_block_number': 6766257,
                                                 'tx_block_number': 6766257,
                                             })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 7450116,
                                               'tx_block_number': 7450116,
                                           })
