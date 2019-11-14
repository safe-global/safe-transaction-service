from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import ProxyFactory, SafeMasterCopy


class Command(BaseCommand):
    help = 'Setup Transaction Service For Rinkeby'

    def handle(self, *args, **options):
        call_command('setup_service')
        SafeMasterCopy.objects.get_or_create(address='0xaE32496491b53841efb51829d6f886387708F99B',
                                             defaults={
                                                 'initial_block_number': 5423491,
                                                 'tx_block_number': 5423491,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                                             defaults={
                                                 'initial_block_number': 4110083,
                                                 'tx_block_number': 4110083,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0x8942595A2dC5181Df0465AF0D7be08c8f23C93af',
                                             defaults={
                                                 'initial_block_number': 3392692,
                                                 'tx_block_number': 3392692,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0x2727D69C0BD14B1dDd28371B8D97e808aDc1C2f7',
                                             defaults={
                                                 'initial_block_number': 3055781,
                                                 'tx_block_number': 3055781,
                                             })

        ProxyFactory.objects.get_or_create(address='0x50e55Af101C777bA7A1d560a774A82eF002ced9F',
                                           defaults={
                                               'initial_block_number': 5423494,
                                               'tx_block_number': 5423494,
                                           })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 4110083,
                                               'tx_block_number': 4110083,
                                           })
