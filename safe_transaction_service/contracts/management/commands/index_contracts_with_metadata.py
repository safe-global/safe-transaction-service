from django.core.management.base import BaseCommand

from ...tasks import (create_missing_contracts_with_metadata_task,
                      reindex_contracts_without_metadata_task)


class Command(BaseCommand):
    help = 'Index contracts from etherscan/sourcify'

    def add_arguments(self, parser):
        parser.add_argument('--reindex', help='Try to fetch contract names/ABIS for contracts already indexed',
                            action='store_true', default=False)
        parser.add_argument('--sync', help="Don't trigger an async task", action='store_true', default=False)

    def handle(self, *args, **options):
        reindex = options['reindex']
        sync = options['sync']

        if reindex:
            task = reindex_contracts_without_metadata_task
        else:
            task = create_missing_contracts_with_metadata_task

        self.stdout.write(self.style.SUCCESS('Triggering task'))
        if sync:
            task()
            self.stdout.write(self.style.SUCCESS('Processing finished'))
        else:
            task.delay()
            self.stdout.write(self.style.SUCCESS('Task was sent'))
