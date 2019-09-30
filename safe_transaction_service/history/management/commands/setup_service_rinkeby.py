from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import ProxyFactory, SafeMasterCopy


class Command(BaseCommand):
    help = 'Setup Transaction Service For Rinkeby'

    def handle(self, *args, **options):
        call_command('setup_service')
        SafeMasterCopy.objects.get_or_create(address='0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                                             defaults={
                                                 'initial_block_number': 4110083,
                                                 'tx_block_number': 4110083,
                                             })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 4110083,
                                               'tx_block_number': 4110083,
                                           })
