from typing import NamedTuple, Tuple

from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork

from ...models import ProxyFactory, SafeMasterCopy


class CeleryTaskConfiguration(NamedTuple):
    name: str
    description: str
    interval: int
    period: str

    def create_task(self) -> Tuple[PeriodicTask, bool]:
        interval, _ = IntervalSchedule.objects.get_or_create(every=self.interval, period=self.period)
        periodic_task, created = PeriodicTask.objects.get_or_create(task=self.name,
                                                                    defaults={
                                                                        'name': self.description,
                                                                        'interval': interval
                                                                    })
        if periodic_task.interval != interval:
            periodic_task.interval = interval
            periodic_task.save(update_fields=['interval'])

        return periodic_task, created


class Command(BaseCommand):
    help = 'Setup Transaction Service Required Tasks'
    tasks = [
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_internal_txs_task',
                                'Index Internal Txs', 13, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_new_proxies_task',
                                'Index new Proxies', 15, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_erc20_events_task',
                                'Index ERC20 Events', 14, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.process_decoded_internal_txs_task',
                                'Process Internal Txs', 2, IntervalSchedule.MINUTES),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.check_reorgs_task',
                                'Check Reorgs', 3, IntervalSchedule.MINUTES),
    ]

    def handle(self, *args, **options):
        for task in self.tasks:
            _, created = task.create_task()
            if created:
                self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task.name))
            else:
                self.stdout.write(self.style.SUCCESS('Task %s was already created' % task.name))

        self.stdout.write(self.style.SUCCESS('Setting up Safe Contract Addresses'))
        ethereum_client = EthereumClientProvider()
        ethereum_network = ethereum_client.get_network()
        if ethereum_network == EthereumNetwork.MAINNET:
            self.stdout.write(self.style.SUCCESS('Setting up Mainnet addresses'))
            self.setup_mainnet()
        elif ethereum_network == EthereumNetwork.RINKEBY:
            self.stdout.write(self.style.SUCCESS('Setting up Rinkeby addresses'))
            self.setup_rinkeby()
        elif ethereum_network == EthereumNetwork.GOERLI:
            self.stdout.write(self.style.SUCCESS('Setting up Goerli addresses'))
            self.setup_goerli()
        elif ethereum_network == EthereumNetwork.KOVAN:
            self.stdout.write(self.style.SUCCESS('Setting up Kovan addresses'))
            self.setup_kovan()
        else:
            self.stdout.write(self.style.WARNING(f'Cannot detect a valid ethereum-network'))

    def setup_mainnet(self):
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

    def setup_rinkeby(self):
        SafeMasterCopy.objects.get_or_create(address='0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                                             defaults={
                                                 'initial_block_number': 5590754,
                                                 'tx_block_number': 5590754,
                                             })
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

        ProxyFactory.objects.get_or_create(address='0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B',
                                           defaults={
                                               'initial_block_number': 5590757,
                                               'tx_block_number': 5590757,
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

    def setup_goerli(self):
        SafeMasterCopy.objects.get_or_create(address='0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                                             defaults={
                                                 'initial_block_number': 1798663,
                                                 'tx_block_number': 1798663,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xaE32496491b53841efb51829d6f886387708F99B',
                                             defaults={
                                                 'initial_block_number': 1631488,
                                                 'tx_block_number': 1631488,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                                             defaults={
                                                 'initial_block_number': 319108,
                                                 'tx_block_number': 319108,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0x8942595A2dC5181Df0465AF0D7be08c8f23C93af',
                                             defaults={
                                                 'initial_block_number': 3392692,
                                                 'tx_block_number': 3392692,
                                             })

        ProxyFactory.objects.get_or_create(address='0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B',
                                           defaults={
                                               'initial_block_number': 1798666,
                                               'tx_block_number': 1798666,
                                           })
        ProxyFactory.objects.get_or_create(address='0x50e55Af101C777bA7A1d560a774A82eF002ced9F',
                                           defaults={
                                               'initial_block_number': 1631491,
                                               'tx_block_number': 1631491,
                                           })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 312509,
                                               'tx_block_number': 312509,
                                           })

    def setup_kovan(self):
        SafeMasterCopy.objects.get_or_create(address='0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                                             defaults={
                                                 'initial_block_number': 15366145,
                                                 'tx_block_number': 15366145,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xaE32496491b53841efb51829d6f886387708F99B',
                                             defaults={
                                                 'initial_block_number': 14740724,
                                                 'tx_block_number': 14740724,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                                             defaults={
                                                 'initial_block_number': 10638132,
                                                 'tx_block_number': 10638132,
                                             })
        SafeMasterCopy.objects.get_or_create(address='0x8942595A2dC5181Df0465AF0D7be08c8f23C93af',
                                             defaults={
                                                 'initial_block_number': 9465686,
                                                 'tx_block_number': 9465686,
                                             })

        ProxyFactory.objects.get_or_create(address='0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B',
                                           defaults={
                                               'initial_block_number': 15366151,
                                               'tx_block_number': 15366151,
                                           })
        ProxyFactory.objects.get_or_create(address='0x50e55Af101C777bA7A1d560a774A82eF002ced9F',
                                           defaults={
                                               'initial_block_number': 14740731,
                                               'tx_block_number': 14740731,
                                           })
        ProxyFactory.objects.get_or_create(address='0x12302fE9c02ff50939BaAaaf415fc226C078613C',
                                           defaults={
                                               'initial_block_number': 10629898,
                                               'tx_block_number': 10629898,
                                           })
