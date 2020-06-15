import os

from django.conf import settings
from django.core.management.base import BaseCommand

from ethereum.utils import checksum_encode

from ...models import Token
from ...token_repository import TokenRepository


class Command(BaseCommand):
    help = 'Update list of tokens'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('base-url', help='Relay base url', type=str)

    def handle(self, *args, **options):
        base_url = options['base-url']
