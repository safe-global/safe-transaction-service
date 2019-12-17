from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import ProxyFactory, SafeMasterCopy


class Command(BaseCommand):
    help = 'Setup Transaction Service For Mainnet'

    def handle(self, *args, **options):
        call_command('setup_service')

        SafeMasterCopy.objects.get_or_create(address='0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                                             defaults={
                                                 'initial_block_number': 9084503,
                                                 'tx_block_number': 9084503,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xaE32496491b53841efb51829d6f886387708F99B',
                                             defaults={
                                                 'initial_block_number': 8915728,
                                                 'tx_block_number': 8915728,
                                             })
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
        SafeMasterCopy.objects.get_or_create(address='0xAC6072986E985aaBE7804695EC2d8970Cf7541A2',
                                             defaults={
                                                 'initial_block_number': 6569433,
                                                 'tx_block_number': 6569433,
                                             })

        ProxyFactory.objects.get_or_create(address='0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B',
                                           defaults={
                                               'initial_block_number': 9084508,
                                               'tx_block_number': 9084508,
                                           })
        ProxyFactory.objects.get_or_create(address='0x50e55Af101C777bA7A1d560a774A82eF002ced9F',
                                           defaults={
                                               'initial_block_number': 8915731,
                                               'tx_block_number': 8915731,
                                           })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 7450116,
                                               'tx_block_number': 7450116,
                                           })
