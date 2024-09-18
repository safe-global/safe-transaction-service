from dataclasses import dataclass
from typing import Sequence, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Min

from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.safe.addresses import MASTER_COPIES, PROXY_FACTORIES

from ...models import IndexingStatus, IndexingStatusType, ProxyFactory, SafeMasterCopy


@dataclass
class CronDefinition:
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


@dataclass
class CeleryTaskConfiguration:
    name: str
    description: str
    interval: int = 0
    period: str = None
    cron: CronDefinition = None
    enabled: bool = True

    def create_task(self) -> Tuple[PeriodicTask, bool]:
        assert self.period or self.cron, "Task must define period or cron"
        if self.period:
            interval_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=self.interval, period=self.period
            )
            defaults = {
                "name": self.description,
                "interval": interval_schedule,
                "enabled": self.enabled,
            }
        else:
            crontab_schedule, _ = CrontabSchedule.objects.get_or_create(
                minute=self.cron.minute,
                hour=self.cron.hour,
                day_of_week=self.cron.day_of_week,
                day_of_month=self.cron.day_of_month,
                month_of_year=self.cron.month_of_year,
            )
            defaults = {
                "name": self.description,
                "crontab": crontab_schedule,
                "enabled": self.enabled,
            }

        periodic_task, created = PeriodicTask.objects.get_or_create(
            task=self.name,
            defaults=defaults,
        )
        if not created:
            periodic_task.name = self.description
            if self.period:
                periodic_task.interval = interval_schedule
            else:
                periodic_task.crontab = crontab_schedule

            periodic_task.enabled = self.enabled
            periodic_task.save()

        return periodic_task, created


TASKS = [
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.check_reorgs_task",
        description="Check Reorgs (every minute)",
        cron=CronDefinition(),  # cron every minute * * * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.check_sync_status_task",
        description="Check Sync status (every 10 minutes)",
        cron=CronDefinition(minute="*/10"),  # cron every 10 minutes */10 * * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.index_internal_txs_task",
        description="Index Internal Txs (every 5 seconds)",
        interval=5,
        period=IntervalSchedule.SECONDS,
        enabled=not settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.index_safe_events_task",
        description="Index Safe events (L2) (every 5 seconds)",
        interval=5,
        period=IntervalSchedule.SECONDS,
        enabled=settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.index_new_proxies_task",
        description="Index new Proxies (every 15 seconds)",
        interval=15,
        period=IntervalSchedule.SECONDS,
        enabled=settings.ETH_L2_NETWORK,
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.index_erc20_events_task",
        description="Index ERC20/721 Events (every 14 seconds)",
        interval=14,
        period=IntervalSchedule.SECONDS,
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.reindex_mastercopies_last_hours_task",
        description="Reindex master copies for the last hours (every 2 hours at minute 0)",
        cron=CronDefinition(
            minute=0, hour="*/2"
        ),  # Every 2 hours at minute 0 - * */2 * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.reindex_erc20_erc721_last_hours_task",
        description="Reindex erc20/erc721 for the last hours (every 2 hours at minute 30)",
        cron=CronDefinition(
            minute=30, hour="*/2"
        ),  # Every 2 hours at minute 30 - 30 */2 * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.process_decoded_internal_txs_task",
        description="Process Internal Txs (every 20 minutes)",
        cron=CronDefinition(minute="*/20"),  # Every 20 minutes - */20 * * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.history.tasks.remove_not_trusted_multisig_txs_task",
        description="Remove older than 1 month not trusted Multisig Txs (every day at 00:00)",
        cron=CronDefinition(minute=0, hour=0),  # Every day at 00:00 - 0 0 * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.contracts.tasks.create_missing_contracts_with_metadata_task",
        description="Index contract names and ABIs (every hour at minute 0)",
        cron=CronDefinition(minute=0),  # Every hour at minute 0 - 0 * * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.contracts.tasks.create_missing_multisend_contracts_with_metadata_task",
        description="Index contract names and ABIs from MultiSend transactions (every 6 hours at minute 0)",
        cron=CronDefinition(minute=0, hour="*/6"),  # Every 6 hours - 0 */6 * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.contracts.tasks.reindex_contracts_without_metadata_task",
        description="Reindex contracts with missing names or ABIs (every sunday at 00:00)",
        cron=CronDefinition(minute=0, hour=0, day_of_week=0),  # Every sunday 0 0 * * 0
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.tokens.tasks.fix_pool_tokens_task",
        description="Fix Pool Token Names (every hour at minute 0)",
        cron=CronDefinition(minute=0),  # Every hour at minute 0 - 0 * * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.tokens.tasks.update_token_info_from_token_list_task",
        description="Update Token info from token list (every day at 00:00)",
        cron=CronDefinition(minute=0, hour=0),  # Every day at 00:00 - 0 0 * * *
    ),
    CeleryTaskConfiguration(
        name="safe_transaction_service.analytics.tasks.get_transactions_per_safe_app_task",
        description="Run query to get number of transactions grouped by safe-app (Every sunday at 00:00)",
        cron=CronDefinition(minute=0, hour=0, day_of_week=0),  # Every sunday 0 0 * * 0
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
        ethereum_client = get_auto_ethereum_client()
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
        try:
            indexing_status = IndexingStatus.objects.get_erc20_721_indexing_status()
        except IndexingStatus.DoesNotExist:
            indexing_status = IndexingStatus.objects.create(
                indexing_type=IndexingStatusType.ERC20_721_EVENTS.value, block_number=0
            )

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
