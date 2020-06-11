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
        parser.add_argument('--pages', help='Number of pages of tokens on etherscan to scrap', type=int)
        parser.add_argument('--download-icons', help='Download icons', action='store_true')
        parser.add_argument('--download-folder', help='Download folder. It implies --download')
        parser.add_argument('--store-db', help='Store tokens in db', action='store_true')

    def handle(self, *args, **options):
        pages = options['pages'] or 3
        download = options['download_icons'] or options['download_folder']
        download_folder = options['download_folder'] or os.path.join(settings.STATIC_ROOT, 'tokens')
        store_db = options['store_db']
        token_repository = TokenRepository()
        tokens = token_repository.get_tokens(pages=pages)
        self.stdout.write(self.style.SUCCESS(str(tokens)))
        if store_db:
            for i, token in enumerate(tokens):
                symbol = token['symbol']
                relevance = 0 if symbol == 'GNO' else i + 1
                token_db, created = Token.objects.get_or_create(
                    address=checksum_encode(token['address']),
                    defaults={
                        'name': token['name'],
                        'symbol': symbol,
                        'description': token['description'],
                        'decimals': token['decimals'],
                        'logo_uri': token['logo_url'] if token['logo_url'] else '',
                        'website_uri': token['website_url'],
                        'gas': False,
                        'relevance': relevance
                    }
                )
                if token_db.relevance != relevance:
                    token_db.relevance = relevance
                    token_db.save(update_fields=['relevance'])
                    self.stdout.write(self.style.SUCCESS('%s changed relevance to %d' % (token['name'], relevance)))

                if created:
                    self.stdout.write(self.style.SUCCESS('Inserted new token %s' % token['name']))

        if download:
            token_repository.download_images_for_tokens(folder=download_folder,
                                                        token_addresses=[token['address'] for token in tokens])
