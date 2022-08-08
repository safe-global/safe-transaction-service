from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork

from ...models import ProxyFactory, SafeMasterCopy


@dataclass
class CeleryTaskConfiguration:
    name: str
    description: str
    interval: int
    period: str
    enabled: bool = True

    def create_task(self) -> Tuple[PeriodicTask, bool]:
        interval_schedule, _ = IntervalSchedule.objects.get_or_create(
            every=self.interval, period=self.period
        )
        periodic_task, created = PeriodicTask.objects.get_or_create(
            task=self.name,
            defaults={
                "name": self.description,
                "interval": interval_schedule,
                "enabled": self.enabled,
            },
        )
        if not created:
            periodic_task.name = self.description
            periodic_task.interval = interval_schedule
            periodic_task.enabled = self.enabled
            periodic_task.save()

        return periodic_task, created


TASKS = [
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.check_reorgs_task",
        "Check Reorgs",
        3,
        IntervalSchedule.MINUTES,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.check_sync_status_task",
        "Check Sync status",
        10,
        IntervalSchedule.MINUTES,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.index_internal_txs_task",
        "Index Internal Txs",
        5,
        IntervalSchedule.SECONDS,
        enabled=not settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.index_safe_events_task",
        "Index Safe events (L2)",
        5,
        IntervalSchedule.SECONDS,
        enabled=settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.index_new_proxies_task",
        "Index new Proxies",
        15,
        IntervalSchedule.SECONDS,
        enabled=settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.index_erc20_events_task",
        "Index ERC20/721 Events",
        14,
        IntervalSchedule.SECONDS,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.reindex_last_hours_task",
        "Reindex master copies for the last hours",
        110,
        IntervalSchedule.MINUTES,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.history.tasks.process_decoded_internal_txs_task",
        "Process Internal Txs",
        20,
        IntervalSchedule.MINUTES,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.contracts.tasks.create_missing_contracts_with_metadata_task",
        "Index contract names and ABIs",
        1,
        IntervalSchedule.HOURS,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.contracts.tasks.create_missing_multisend_contracts_with_metadata_task",
        "Index contract names and ABIs from MultiSend transactions",
        6,
        IntervalSchedule.HOURS,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.contracts.tasks.reindex_contracts_without_metadata_task",
        "Reindex contracts with missing names or ABIs",
        7,
        IntervalSchedule.DAYS,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.tokens.tasks.fix_pool_tokens_task",
        "Fix Pool Token Names",
        1,
        IntervalSchedule.HOURS,
    ),
]

MASTER_COPIES: Dict[EthereumNetwork, List[Tuple[str, int, str]]] = {
    EthereumNetwork.MAINNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 12504423, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 12504268, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 10329734, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 9084503, "1.1.1"),
        ("0xaE32496491b53841efb51829d6f886387708F99B", 8915728, "1.1.0"),
        ("0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A", 7457553, "1.0.0"),
        ("0x8942595A2dC5181Df0465AF0D7be08c8f23C93af", 6766257, "0.1.0"),
        ("0xAC6072986E985aaBE7804695EC2d8970Cf7541A2", 6569433, "0.0.2"),
    ],
    EthereumNetwork.RINKEBY: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 8527380, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 8527381, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 6723632, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 5590754, "1.1.1"),
        ("0xaE32496491b53841efb51829d6f886387708F99B", 5423491, "1.1.0"),
        ("0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A", 4110083, "1.0.0"),
        ("0x8942595A2dC5181Df0465AF0D7be08c8f23C93af", 3392692, "0.1.0"),
        ("0x2727D69C0BD14B1dDd28371B8D97e808aDc1C2f7", 3055781, "0.0.2"),
    ],
    EthereumNetwork.GOERLI: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 4854168, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 4854169, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 2930373, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 1798663, "1.1.1"),
        ("0xaE32496491b53841efb51829d6f886387708F99B", 1631488, "1.1.0"),
        ("0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A", 319108, "1.0.0"),
        ("0x8942595A2dC5181Df0465AF0D7be08c8f23C93af", 34096, "0.1.0"),
    ],
    EthereumNetwork.KOVAN: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 25059609, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 25059611, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 19242615, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 15366145, "1.1.1"),
        ("0xaE32496491b53841efb51829d6f886387708F99B", 14740724, "1.1.0"),
        ("0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A", 10638132, "1.0.0"),
        ("0x8942595A2dC5181Df0465AF0D7be08c8f23C93af", 9465686, "0.1.0"),
    ],
    EthereumNetwork.XDAI: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 16236936, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 16236998, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 10612049, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 10045292, "1.1.1"),
        ("0x2CB0ebc503dE87CFD8f0eCEED8197bF7850184ae", 12529466, "1.1.1+Circles"),
        ("0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A", 19560130, "1.0.0"),
    ],
    EthereumNetwork.ENERGY_WEB_CHAIN: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 12028662, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 12028664, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 6398655, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 6399212, "1.1.1"),
    ],
    EthereumNetwork.VOLTA: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 11942450, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 11942451, "1.3.0"),
        ("0x6851D6fDFAfD08c0295C392436245E5bc78B0185", 6876086, "1.2.0"),
        ("0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F", 6876642, "1.1.1"),
    ],
    EthereumNetwork.MATIC: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 14306478, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 14306478, "1.3.0"),
    ],
    EthereumNetwork.MUMBAI: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 13736914, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 13736914, "1.3.0"),
    ],
    EthereumNetwork.ARBITRUM: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 1146, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 1140, "1.3.0"),
    ],
    EthereumNetwork.ARBITRUM_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 57070, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 57070, "1.3.0"),
    ],
    EthereumNetwork.BINANCE: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 8485899, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 8485903, "1.3.0"),
    ],
    EthereumNetwork.CELO: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 8944350, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 8944351, "1.3.0"),
    ],
    EthereumNetwork.AVALANCHE: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 4_949_507, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 4_949_512, "1.3.0"),
    ],
    EthereumNetwork.MOON_MOONRIVER: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 707_738, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 707_741, "1.3.0"),
    ],
    EthereumNetwork.MOON_MOONBASE: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 939_244, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 939_246, "1.3.0"),
    ],
    EthereumNetwork.FUSE_MAINNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 12_725_078, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 12_725_081, "1.3.0"),
    ],
    EthereumNetwork.FUSE_SPARK: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 1_010_518, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 1_010_520, "1.3.0"),
    ],
    EthereumNetwork.OLYMPUS: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 1227, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 1278, "1.3.0"),
    ],
    EthereumNetwork.OPTIMISTIC: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 173749, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 173751, "1.3.0"),
    ],
    EthereumNetwork.BOBA_RINKEBY: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 18854, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 18855, "1.3.0"),
    ],
    EthereumNetwork.BOBA: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 170908, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 170910, "1.3.0"),
    ],
    EthereumNetwork.AURORA: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 52494580, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 52494580, "1.3.0"),
    ],
    EthereumNetwork.METIS_TESTNET: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 56124, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 56125, "1.3.0"),
    ],
    EthereumNetwork.METIS: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 61767, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 61768, "1.3.0"),
    ],
    EthereumNetwork.SHYFT: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 1000, "1.3.0+L2"),  # v1.3.0
    ],
    EthereumNetwork.SHYFT_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 1984340, "1.3.0+L2"),  # v1.3.0
    ],
    EthereumNetwork.REI_MAINNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 2388036, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 2388042, "1.3.0"),
    ],
    EthereumNetwork.REI_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 748810, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 748815, "1.3.0"),
    ],
    EthereumNetwork.METER: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 23863901, "1.3.0+L2")  # v1.3.0
    ],
    EthereumNetwork.METER_TESTNET: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 15035438, "1.3.0+L2")  # v1.3.0
    ],
    EthereumNetwork.EURUS_MAINNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 7127163, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 7127166, "1.3.0"),
    ],
    EthereumNetwork.EURUS_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 12845441, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 12845443, "1.3.0"),
    ],
    EthereumNetwork.VENIDIUM_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 761243, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 761244, "1.3.0"),
    ],
    EthereumNetwork.GODWOKEN_TESTNET: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 93204, "1.3.0+L2"),
        ("0x69f4D1788e39c87893C980c06EdF4b7f686e2938", 93168, "1.3.0"),
    ],
    EthereumNetwork.KLAY_BAOBAB: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 93821635, "1.3.0+L2"),
    ],
    EthereumNetwork.KLAY_CYPRESS: [
        ("0xfb1bffC9d739B8D520DaF37dF666da4C687191EA", 93507490, "1.3.0+L2"),
    ],
    EthereumNetwork.MILKOMEDA_C1_TESTNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 5080339, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 5080357, "1.3.0"),
    ],
    EthereumNetwork.MILKOMEDA_C1_MAINNET: [
        ("0x3E5c63644E683549055b9Be8653de26E0B4CD36E", 4896727, "1.3.0+L2"),
        ("0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552", 4896733, "1.3.0"),
    ],
}

PROXY_FACTORIES: Dict[EthereumNetwork, List[Tuple[str, int]]] = {
    EthereumNetwork.MAINNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 12504126),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 9084508),  # v1.1.1
        ("0x50e55Af101C777bA7A1d560a774A82eF002ced9F", 8915731),  # v1.1.0
        ("0x12302fE9c02ff50939BaAaaf415fc226C078613C", 7450116),  # v1.0.0
    ],
    EthereumNetwork.RINKEBY: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 8493997),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 5590757),
        ("0x50e55Af101C777bA7A1d560a774A82eF002ced9F", 5423494),
        ("0x12302fE9c02ff50939BaAaaf415fc226C078613C", 4110083),
    ],
    EthereumNetwork.GOERLI: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 4695402),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 1798666),
        ("0x50e55Af101C777bA7A1d560a774A82eF002ced9F", 1631491),
        ("0x12302fE9c02ff50939BaAaaf415fc226C078613C", 312509),
    ],
    EthereumNetwork.KOVAN: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 25059601),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 15366151),
        ("0x50e55Af101C777bA7A1d560a774A82eF002ced9F", 14740731),
        ("0x12302fE9c02ff50939BaAaaf415fc226C078613C", 10629898),
    ],
    EthereumNetwork.XDAI: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 16236878),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 10045327),  # v1.1.1
        ("0x12302fE9c02ff50939BaAaaf415fc226C078613C", 17677119),  # v1.0.0
    ],
    EthereumNetwork.ENERGY_WEB_CHAIN: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 12028652),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 6399239),
    ],
    EthereumNetwork.VOLTA: [
        # ('0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2', 0),  # v1.3.0
        ("0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B", 6876681),
    ],
    EthereumNetwork.MATIC: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 14306478),  # v1.3.0
    ],
    EthereumNetwork.MUMBAI: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 13736914),  # v1.3.0
    ],
    EthereumNetwork.ARBITRUM: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 1140),  # v1.3.0
    ],
    EthereumNetwork.ARBITRUM_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 57070),  # v1.3.0
    ],
    EthereumNetwork.BINANCE: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 8485873),  # v1.3.0
    ],
    EthereumNetwork.CELO: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 8944342),  # v1.3.0
    ],
    EthereumNetwork.AVALANCHE: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 4_949_487),  # v1.3.0
    ],
    EthereumNetwork.MOON_MOONRIVER: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 707_721),  # v1.3.0
    ],
    EthereumNetwork.MOON_MOONBASE: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 939_239),  # v1.3.0
    ],
    EthereumNetwork.FUSE_MAINNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 12_725_072),  # v1.3.0
    ],
    EthereumNetwork.FUSE_SPARK: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 1_010_506),  # v1.3.0
    ],
    EthereumNetwork.OLYMPUS: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 1266),  # v1.3.0
    ],
    EthereumNetwork.OPTIMISTIC: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 173709),  # v1.3.0
    ],
    EthereumNetwork.BOBA_RINKEBY: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 18847),  # v1.3.0
    ],
    EthereumNetwork.BOBA: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 170895),  # v1.3.0
    ],
    EthereumNetwork.AURORA: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 52494580),  # v1.3.0
    ],
    EthereumNetwork.METIS_TESTNET: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 56117),  # v1.3.0
    ],
    EthereumNetwork.METIS: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 61758),  # v1.3.0
    ],
    EthereumNetwork.SHYFT: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 2000),  # v1.3.0
    ],
    EthereumNetwork.SHYFT_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 1984340),  # v1.3.0
    ],
    EthereumNetwork.REI_MAINNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 2387999),  # v1.3.0
    ],
    EthereumNetwork.REI_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 748768),  # v1.3.0
    ],
    EthereumNetwork.METER: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 23863720),  # v1.3.0
    ],
    EthereumNetwork.METER_TESTNET: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 15035363),  # v1.3.0
    ],
    EthereumNetwork.EURUS_MAINNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 7127155),  # v1.3.0
    ],
    EthereumNetwork.EURUS_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 12845425),  # v1.3.0
    ],
    EthereumNetwork.VENIDIUM_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 761231),  # v1.3.0
    ],
    EthereumNetwork.GODWOKEN_TESTNET: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 93108),  # v1.3.0
    ],
    EthereumNetwork.KLAY_BAOBAB: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 93821613),  # v1.3.0
    ],
    EthereumNetwork.KLAY_CYPRESS: [
        ("0xC22834581EbC8527d974F8a1c97E1bEA4EF910BC", 93506870),  # v1.3.0
    ],
    EthereumNetwork.MILKOMEDA_C1_TESTNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 5080303),  # v1.3.0
    ],
    EthereumNetwork.MILKOMEDA_C1_MAINNET: [
        ("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2", 4896699),  # v1.3.0
    ],
}


class Command(BaseCommand):
    help = "Setup Transaction Service Required Tasks"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Removing old tasks"))
        PeriodicTask.objects.filter(
            task__startswith="safe_transaction_service"
        ).delete()
        self.stdout.write(self.style.SUCCESS("Old tasks were removed"))

        for task in TASKS:
            _, created = task.create_task()
            if created:
                self.stdout.write(
                    self.style.SUCCESS("Created Periodic Task %s" % task.name)
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("Task %s was already created" % task.name)
                )

        self.stdout.write(self.style.SUCCESS("Setting up Safe Contract Addresses"))
        ethereum_client = EthereumClientProvider()
        ethereum_network = ethereum_client.get_network()
        if ethereum_network in MASTER_COPIES:
            self.stdout.write(
                self.style.SUCCESS(f"Setting up {ethereum_network.name} safe addresses")
            )
            self._setup_safe_master_copies(MASTER_COPIES[ethereum_network])
        if ethereum_network in PROXY_FACTORIES:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Setting up {ethereum_network.name} proxy factory addresses"
                )
            )
            self._setup_safe_proxy_factories(PROXY_FACTORIES[ethereum_network])

        if not (
            ethereum_network in MASTER_COPIES and ethereum_network in PROXY_FACTORIES
        ):
            self.stdout.write(
                self.style.WARNING("Cannot detect a valid ethereum-network")
            )

    def _setup_safe_master_copies(
        self, safe_master_copies: Sequence[Tuple[str, int, str]]
    ):
        for address, initial_block_number, version in safe_master_copies:
            safe_master_copy, _ = SafeMasterCopy.objects.get_or_create(
                address=address,
                defaults={
                    "initial_block_number": initial_block_number,
                    "tx_block_number": initial_block_number,
                    "version": version,
                    "l2": version.endswith("+L2"),
                },
            )
            if (
                safe_master_copy.version != version
                or safe_master_copy.initial_block_number != initial_block_number
            ):
                safe_master_copy.version = initial_block_number
                safe_master_copy.version = version
                safe_master_copy.save(update_fields=["initial_block_number", "version"])

    def _setup_safe_proxy_factories(
        self, safe_proxy_factories: Sequence[Tuple[str, int]]
    ):
        for address, initial_block_number in safe_proxy_factories:
            ProxyFactory.objects.get_or_create(
                address=address,
                defaults={
                    "initial_block_number": initial_block_number,
                    "tx_block_number": initial_block_number,
                },
            )
