from dataclasses import dataclass
from typing import Sequence, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Min

from django_celery_beat.models import IntervalSchedule, PeriodicTask

from gnosis.eth import EthereumClientProvider
from gnosis.safe.addresses import MASTER_COPIES, PROXY_FACTORIES

from ...models import IndexingStatus, ProxyFactory, SafeMasterCopy


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
        1,
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
        "safe_transaction_service.history.tasks.remove_not_trusted_multisig_txs_task",
        "Remove older than 1 month not trusted Multisig Txs",
        1,
        IntervalSchedule.DAYS,
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
    CeleryTaskConfiguration(
        "safe_transaction_service.tokens.tasks.update_token_info_from_token_list_task",
        "Update Token info from token list",
        1,
        IntervalSchedule.DAYS,
    ),
    CeleryTaskConfiguration(
        "safe_transaction_service.analytics.tasks.get_transactions_per_safe_app_task",
        "Run query to get number of transactions grouped by safe-app",
        7,
        IntervalSchedule.DAYS,
    ),
]


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
            self._setup_erc20_indexing()
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

    def _setup_erc20_indexing(self) -> bool:
        """
        Update ERC20/721 indexing status if `indexing block number` is less
        than `Master copies` block deployments, as it sounds like a configuration error

        :return: `True` if updated, `False` otherwise
        """
        indexing_status = IndexingStatus.objects.get_erc20_721_indexing_status()

        queryset = (
            SafeMasterCopy.objects.filter(l2=True)
            if settings.ETH_L2_NETWORK
            else SafeMasterCopy.objects.all()
        )
        min_master_copies_block_number = queryset.aggregate(
            min_master_copies_block_number=Min("initial_block_number")
        )["min_master_copies_block_number"]
        block_number = (
            min_master_copies_block_number if min_master_copies_block_number else 0
        )

        if indexing_status.block_number < block_number:
            indexing_status.block_number = block_number
            indexing_status.save(update_fields=["block_number"])
            return True
        return False
