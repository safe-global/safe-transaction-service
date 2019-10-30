from typing import NamedTuple, Tuple

from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask


class CeleryTaskConfiguration(NamedTuple):
    name: str
    description: str
    interval: int
    period: str

    def create_task(self) -> Tuple[PeriodicTask, bool]:
        interval, _ = IntervalSchedule.objects.get_or_create(every=self.interval, period=self.period)
        return PeriodicTask.objects.get_or_create(task=self.name,
                                                  defaults={
                                                      'name': self.description,
                                                      'interval': interval
                                                  })


class Command(BaseCommand):
    help = 'Setup Transaction Service Required Tasks'
    tasks = [
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_internal_txs_task',
                                'Index Internal Txs', 14, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_new_proxies_task',
                                'Index new Proxies', 15, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.index_erc20_events_task',
                                'Index ERC20 Events', 15, IntervalSchedule.SECONDS),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.process_decoded_internal_txs_task',
                                'Process Internal Txs', 2, IntervalSchedule.MINUTES),
        CeleryTaskConfiguration('safe_transaction_service.history.tasks.check_reorgs_task',
                                'Check Reorgs', 90, IntervalSchedule.SECONDS),
    ]

    def handle(self, *args, **options):

        for task in self.tasks:
            _, created = task.create_task()
            if created:
                self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task.name))
            else:
                self.stdout.write(self.style.SUCCESS('Task %s was already created' % task.name))
