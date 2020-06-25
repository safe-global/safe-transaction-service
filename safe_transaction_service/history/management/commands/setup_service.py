from typing import NamedTuple, Sequence, Tuple

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
            self.stdout.write(self.style.SUCCESS(f'Setting up {ethereum_network.name} addresses'))
            self.setup_mainnet()
        elif ethereum_network == EthereumNetwork.RINKEBY:
            self.stdout.write(self.style.SUCCESS(f'Setting up {ethereum_network.name} addresses'))
            self.setup_rinkeby()
        elif ethereum_network == EthereumNetwork.GOERLI:
            self.stdout.write(self.style.SUCCESS(f'Setting up {ethereum_network.name} addresses'))
            self.setup_goerli()
        elif ethereum_network == EthereumNetwork.KOVAN:
            self.stdout.write(self.style.SUCCESS(f'Setting up {ethereum_network.name} addresses'))
            self.setup_kovan()
        else:
            self.stdout.write(self.style.WARNING('Cannot detect a valid ethereum-network'))

    def _setup_safe_master_copies(self, safe_master_copies: Sequence[Tuple[str, int]]):
        for address, initial_block_number in safe_master_copies:
            SafeMasterCopy.objects.get_or_create(address=address,
                                                 defaults={
                                                     'initial_block_number': initial_block_number,
                                                     'tx_block_number': initial_block_number,
                                                 })

    def _setup_safe_proxy_factories(self, safe_proxy_factories: Sequence[Tuple[str, int]]):
        for address, initial_block_number in safe_proxy_factories:
            ProxyFactory.objects.get_or_create(address=address,
                                               defaults={
                                                   'initial_block_number': initial_block_number,
                                                   'tx_block_number': initial_block_number,
                                               })

    def setup_mainnet(self):
        safe_master_copies = [
            ('0x6851D6fDFAfD08c0295C392436245E5bc78B0185', 10329734),  # v1.2.0
            ('0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F', 9084503),   # v1.1.1
            ('0xaE32496491b53841efb51829d6f886387708F99B', 8915728),   # v1.1.0
            ('0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A', 7457553),   # v1.0.0
            ('0x8942595A2dC5181Df0465AF0D7be08c8f23C93af', 6766257),   # v0.1.0
            ('0xAC6072986E985aaBE7804695EC2d8970Cf7541A2', 6569433),   # v0.0.2
        ]

        safe_proxy_factories = [
            ('0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B', 9084508),
            ('0x50e55Af101C777bA7A1d560a774A82eF002ced9F', 8915731),
            ('0x12302fE9c02ff50939BaAaaf415fc226C078613C', 7450116),
        ]

        self._setup_safe_master_copies(safe_master_copies)
        self._setup_safe_proxy_factories(safe_proxy_factories)

    def setup_rinkeby(self):
        safe_master_copies = [
            ('0x6851D6fDFAfD08c0295C392436245E5bc78B0185', 6723632),  # v1.2.0
            ('0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F', 5590754),  # v1.1.1
            ('0xaE32496491b53841efb51829d6f886387708F99B', 5423491),  # v1.1.0
            ('0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A', 4110083),  # v1.0.0
            ('0x8942595A2dC5181Df0465AF0D7be08c8f23C93af', 3392692),  # v0.1.0
            ('0x2727D69C0BD14B1dDd28371B8D97e808aDc1C2f7', 3055781),  # v0.0.2
        ]

        safe_proxy_factories = [
            ('0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B', 5590757),
            ('0x50e55Af101C777bA7A1d560a774A82eF002ced9F', 5423494),
            ('0x12302fE9c02ff50939BaAaaf415fc226C078613C', 4110083),
        ]

        self._setup_safe_master_copies(safe_master_copies)
        self._setup_safe_proxy_factories(safe_proxy_factories)

    def setup_goerli(self):
        safe_master_copies = [
            ('0x6851D6fDFAfD08c0295C392436245E5bc78B0185', 2930373),  # v1.2.0
            ('0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F', 1798663),  # v1.1.1
            ('0xaE32496491b53841efb51829d6f886387708F99B', 1631488),  # v1.1.0
            ('0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A', 319108),   # v1.0.0
            ('0x8942595A2dC5181Df0465AF0D7be08c8f23C93af', 3392692),  # v0.1.0
        ]

        safe_proxy_factories = [
            ('0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B', 1798666),
            ('0x50e55Af101C777bA7A1d560a774A82eF002ced9F', 1631491),
            ('0x12302fE9c02ff50939BaAaaf415fc226C078613C', 312509),
        ]

        self._setup_safe_master_copies(safe_master_copies)
        self._setup_safe_proxy_factories(safe_proxy_factories)

    def setup_kovan(self):
        safe_master_copies = [
            ('0x6851D6fDFAfD08c0295C392436245E5bc78B0185', 19242615),  # v1.2.0
            ('0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F', 15366145),  # v1.1.1
            ('0xaE32496491b53841efb51829d6f886387708F99B', 14740724),  # v1.1.0
            ('0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A', 10638132),  # v1.0.0
            ('0x8942595A2dC5181Df0465AF0D7be08c8f23C93af', 9465686),   # v0.1.0
        ]

        safe_proxy_factories = [
            ('0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B', 15366151),
            ('0x50e55Af101C777bA7A1d560a774A82eF002ced9F', 14740731),
            ('0x12302fE9c02ff50939BaAaaf415fc226C078613C', 10629898),
        ]

        self._setup_safe_master_copies(safe_master_copies)
        self._setup_safe_proxy_factories(safe_proxy_factories)
