import logging
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from gnosis.eth.django.models import EthereumAddressField

logger = logging.getLogger(__name__)


class TokenManager(models.Manager):
    def create(self, **kwargs):
        for field in ('name', 'symbol'):
            kwargs[field] = kwargs[field][:60]
        return super().create(**kwargs)


class TokenQuerySet(models.QuerySet):
    erc721_query = Q(decimals=None)
    erc20_query = ~erc721_query

    def erc20(self):
        return self.filter(self.erc20_query)

    def erc721(self):
        return self.filter(self.erc721_query)


class Token(models.Model):
    objects = TokenManager.from_queryset(TokenQuerySet)()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=60)
    decimals = models.PositiveSmallIntegerField(db_index=True,
                                                null=True, blank=True)  # For ERC721 tokens `decimals=None`
    logo_uri = models.CharField(blank=True, max_length=300, default='')
    trusted = models.BooleanField(default=False)
    spam = models.BooleanField(default=False)  # Spam and trusted cannot be both True

    def __str__(self):
        spam_text = 'SPAM ' if self.spam else ''
        if self.decimals:
            return f'{spam_text}ERC20 - {self.name} - {self.address}'
        else:
            return f'ERC721 - {self.name} - {self.address}'

    def clean(self):
        if self.trusted and self.spam:
            raise ValidationError('Spam and trusted cannot be both `True`')

    def is_erc20(self):
        return self.decimals is not None

    def is_erc721(self):
        return not self.is_erc20()

    def set_trusted(self) -> None:
        self.trusted = True
        return self.save(update_fields=['trusted'])

    def set_spam(self) -> None:
        self.spam = True
        return self.save(update_fields=['spam'])

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
