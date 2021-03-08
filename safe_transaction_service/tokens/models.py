import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from eth_typing import ChecksumAddress

from gnosis.eth import (EthereumClientProvider, InvalidERC20Info,
                        InvalidERC721Info)
from gnosis.eth.django.models import EthereumAddressField

from .clients.zerion_client import (BalancerTokenAdapterClient,
                                    ZerionTokenAdapterClient,
                                    ZerionUniswapV2TokenAdapterClient)
from .constants import ENS_CONTRACTS_WITH_TLD

logger = logging.getLogger(__name__)


class PoolTokenManager(models.Manager):
    def fix_all_pool_tokens(self):
        return self.fix_uniswap_pool_tokens() + self.fix_balancer_pool_tokens()

    def _fix_pool_tokens(self, name: str, zerion_client: ZerionTokenAdapterClient):
        updated = 0
        for token in self.filter(name=name):
            if metadata := zerion_client.get_metadata(token.address):
                token.name = name + ' ' + metadata.name
                token.name = token.name[:60]
                token.save(update_fields=['name'])
                updated += 1
        return updated

    def fix_uniswap_pool_tokens(self) -> int:
        """
        All Uniswap V2 tokens have the same name: "Uniswap V2". This method will return better names
        :return: Number of pool tokens fixed
        """
        zerion_client = ZerionUniswapV2TokenAdapterClient(EthereumClientProvider())
        return self._fix_pool_tokens('Uniswap V2', zerion_client)

    def fix_balancer_pool_tokens(self) -> int:
        """
        All Uniswap V2 tokens have the same name: "Uniswap V2". This method will return better names
        :return: Number of pool tokens fixed
        """
        zerion_client = BalancerTokenAdapterClient(EthereumClientProvider())
        return self._fix_pool_tokens('Balancer Pool Token', zerion_client)


class TokenManager(models.Manager):
    def create(self, **kwargs):
        for field in ('name', 'symbol'):
            kwargs[field] = kwargs[field][:60]
        return super().create(**kwargs)

    def create_from_blockchain(self, token_address: ChecksumAddress) -> Optional['Token']:
        ethereum_client = EthereumClientProvider()
        if token_address in ENS_CONTRACTS_WITH_TLD:  # Special case for ENS
            return self.create(address=token_address,
                               name='Ethereum Name Service',
                               symbol='ENS',
                               logo_uri='ENS.png',
                               decimals=None,
                               trusted=True)
        try:
            logger.debug('Querying blockchain for info for erc20 token=%s', token_address)
            erc_info = ethereum_client.erc20.get_info(token_address)
            decimals = erc_info.decimals
        except InvalidERC20Info:
            logger.debug('Erc20 token not found, querying blockchain for info for erc721 token=%s', token_address)
            try:
                erc_info = ethereum_client.erc721.get_info(token_address)
                decimals = None
            except InvalidERC721Info:
                logger.debug('Cannot find anything on blockchain for token=%s', token_address)
                return None

        # If symbol is way bigger than name (by 5 characters), swap them (e.g. POAP)
        name, symbol = erc_info.name, erc_info.symbol
        if (len(name) - len(symbol)) < -5:
            name, symbol = symbol, name
        return self.create(address=token_address,
                           name=name,
                           symbol=symbol,
                           decimals=decimals)


class TokenQuerySet(models.QuerySet):
    erc721_query = Q(decimals=None)
    erc20_query = ~erc721_query

    def erc20(self):
        return self.filter(self.erc20_query)

    def erc721(self):
        return self.filter(self.erc721_query)

    def not_spam(self):
        return self.filter(spam=False)

    def trusted(self):
        return self.filter(trusted=True)


class Token(models.Model):
    objects = TokenManager.from_queryset(TokenQuerySet)()
    pool_tokens = PoolTokenManager()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=60)
    decimals = models.PositiveSmallIntegerField(db_index=True,
                                                null=True, blank=True)  # For ERC721 tokens `decimals=None`
    logo_uri = models.CharField(blank=True, max_length=300, default='')
    events_bugged = models.BooleanField(default=False)  # If `True` token does not send `Transfer` event sometimes,
    # like `WETH` on minting
    spam = models.BooleanField(default=False)  # Spam and trusted cannot be both True
    trusted = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(name='token_trusted_idx',
                         fields=['trusted'],
                         condition=Q(trusted=True)),
            models.Index(name='token_events_bugged_idx',
                         fields=['events_bugged'],
                         condition=Q(events_bugged=True)),
        ]

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
