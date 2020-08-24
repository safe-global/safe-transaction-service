import logging
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.db import models

from gnosis.eth.django.models import EthereumAddressField

logger = logging.getLogger(__name__)


class TokenQuerySet(models.QuerySet):
    def erc20(self):
        return self.exclude(decimals=0)

    def erc721(self):
        return self.filter(decimals=0)


class Token(models.Model):
    objects = TokenQuerySet.as_manager()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=60)
    decimals = models.PositiveSmallIntegerField(db_index=True)  # For ERC721 tokens decimals=0
    logo_uri = models.CharField(blank=True, max_length=300, default='')
    trusted = models.BooleanField(default=False)

    def __str__(self):
        if self.decimals:
            return f'ERC20 - {self.name} - {self.address}'
        else:
            return f'ERC721 - {self.name} - {self.address}'

    def set_trusted(self) -> None:
        self.trusted = True
        return self.save(update_fields=['trusted'])

    def get_full_logo_uri(self):
        if urlparse(self.logo_uri).netloc:
            # Absolute uri stored
            return self.logo_uri
        elif self.logo_uri:
            # Just path/filename with extension stored
            return urljoin(settings.TOKENS_LOGO_BASE_URI, self.logo_uri)
        else:
            # Generate logo uri based on configuration
            return urljoin(settings.TOKENS_LOGO_BASE_URI, self.address + settings.TOKENS_LOGO_EXTENSION)
