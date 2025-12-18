import logging
import os
from json import JSONDecodeError
from typing import Optional, TypedDict
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q

import requests
from botocore.exceptions import ClientError
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from imagekit.models import ProcessedImageField
from pilkit.processors import Resize
from safe_eth.eth import InvalidERC20Info, InvalidERC721Info, get_auto_ethereum_client
from safe_eth.eth.django.models import EthereumAddressBinaryField
from web3.exceptions import Web3Exception

from .clients.zerion_client import (
    BalancerTokenAdapterClient,
    ZerionTokenAdapterClient,
    ZerionUniswapV2TokenAdapterClient,
)
from .constants import ENS_CONTRACTS_WITH_TLD
from .exceptions import TokenListRetrievalException

logger = logging.getLogger(__name__)


def get_token_logo_path(instance: "Token", filename):
    # file will be uploaded to MEDIA_ROOT/<address>
    _, extension = os.path.splitext(filename)
    return f"tokens/logos/{instance.address}{extension}"  # extension includes '.'


def get_file_storage():
    if settings.AWS_CONFIGURED:
        from django_s3_storage.storage import S3Storage

        return S3Storage()
    else:
        return default_storage


class PoolTokenManager(models.Manager):
    def fix_all_pool_tokens(self):
        return self.fix_uniswap_pool_tokens() + self.fix_balancer_pool_tokens()

    def _fix_pool_tokens(self, name: str, zerion_client: ZerionTokenAdapterClient):
        updated = 0
        for token in self.filter(name=name):
            if metadata := zerion_client.get_metadata(token.address):
                token.name = name + " " + metadata.name
                token.name = token.name[:60]
                token.save(update_fields=["name"])
                updated += 1
        return updated

    def fix_uniswap_pool_tokens(self) -> int:
        """
        All Uniswap V2 tokens have the same name: "Uniswap V2". This method will return better names
        :return: Number of pool tokens fixed
        """
        zerion_client = ZerionUniswapV2TokenAdapterClient(get_auto_ethereum_client())
        return self._fix_pool_tokens("Uniswap V2", zerion_client)

    def fix_balancer_pool_tokens(self) -> int:
        """
        All Uniswap V2 tokens have the same name: "Uniswap V2". This method will return better names
        :return: Number of pool tokens fixed
        """
        zerion_client = BalancerTokenAdapterClient(get_auto_ethereum_client())
        return self._fix_pool_tokens("Balancer Pool Token", zerion_client)


class TokenManager(models.Manager):
    def create(self, **kwargs):
        for field in ("name", "symbol"):
            kwargs[field] = kwargs[field][:60]
        return super().create(**kwargs)

    def create_from_blockchain(
        self, token_address: ChecksumAddress
    ) -> Optional["Token"]:
        if TokenNotValid.objects.filter(address=token_address).exists():
            # If token is not valid, ignore it
            return None

        ethereum_client = get_auto_ethereum_client()
        if token_address in ENS_CONTRACTS_WITH_TLD:  # Special case for ENS
            return self.create(
                address=token_address,
                name="Ethereum Name Service",
                symbol="ENS",
                logo="tokens/logos/ENS.png",
                decimals=None,
                trusted=True,
            )
        try:
            logger.debug(
                "Querying blockchain for info for erc20 token=%s", token_address
            )
            erc_info = ethereum_client.erc20.get_info(token_address)
            decimals = erc_info.decimals
        except InvalidERC20Info:
            logger.debug(
                "Erc20 token not found, querying blockchain for info for erc721 token=%s",
                token_address,
            )
            try:
                erc_info = ethereum_client.erc721.get_info(token_address)
                # Make sure ERC721 is not indexed as an ERC20 for a node misbehaving
                try:
                    decimals = ethereum_client.erc20.get_decimals(token_address)
                except (Web3Exception, DecodingError, ValueError):
                    decimals = None
            except InvalidERC721Info:
                logger.debug(
                    "Cannot find anything on blockchain for token=%s", token_address
                )
                TokenNotValid.objects.get_or_create(address=token_address)
                return None

        # Ignore tokens with empty name or symbol
        if not erc_info.name or not erc_info.symbol:
            logger.warning(
                "Token with address=%s has not name or symbol", token_address
            )
            TokenNotValid.objects.get_or_create(address=token_address)
            return None

        name_and_symbol: list[str] = []
        for text in (erc_info.name, erc_info.symbol):
            if isinstance(text, str):
                text = text.encode()
            name_and_symbol.append(
                text.decode("utf-8", errors="replace").replace("\x00", "\ufffd")
            )

        name, symbol = name_and_symbol
        # If symbol is way bigger than name (by 5 characters), swap them (e.g. POAP)
        if (len(name) - len(symbol)) < -5:
            name, symbol = symbol, name

        try:
            return self.create(
                address=token_address, name=name, symbol=symbol, decimals=decimals
            )
        except ValueError:
            logger.error(
                "Problem creating token with address=%s name=%s symbol=%s decimals=%s",
                token_address,
                name,
                symbol,
                decimals,
            )
            return None

    def fix_missing_logos(self) -> int:
        """
        Syncs tokens with empty logos with files that exist on S3 and match the address

        :return: Number of synced logos
        """
        synced_logos = 0
        for token in self.without_logo():
            filename = get_token_logo_path(token, f"{token.address}.png")
            token.logo.name = filename
            try:
                if token.logo.size:
                    synced_logos += 1
                    token.save(update_fields=["logo"])
                    logger.info("Found logo on url %s", token.logo.url)
            except (ClientError, FileNotFoundError):  # Depending on aws or filesystem
                logger.error("Error retrieving url %s", token.logo.url)
        return synced_logos


class TokenQuerySet(models.QuerySet):
    erc721_query = Q(decimals=None)
    erc20_query = ~erc721_query
    no_logo_query = Q(logo=None) | Q(logo="")

    def erc20(self):
        return self.filter(self.erc20_query)

    def erc721(self):
        return self.filter(self.erc721_query)

    def spam(self):
        return self.filter(spam=True)

    def not_spam(self):
        return self.filter(spam=False)

    def trusted(self):
        return self.filter(trusted=True)

    def with_logo(self):
        return self.exclude(self.no_logo_query)

    def without_logo(self):
        return self.filter(self.no_logo_query)


class Token(models.Model):
    """Stores metadata about ERC-20 and ERC-721 tokens handled by the service."""

    objects = TokenManager.from_queryset(TokenQuerySet)()
    pool_tokens = PoolTokenManager()
    address = EthereumAddressBinaryField(primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=60)
    decimals = models.PositiveSmallIntegerField(
        db_index=True,
        null=True,
        blank=True,
        help_text="Number of decimals. For ERC721 tokens decimals must be `None`",
    )
    logo = ProcessedImageField(
        blank=True,
        default="",
        upload_to=get_token_logo_path,
        storage=get_file_storage,
        format="PNG",
        processors=[Resize(256, 256, upscale=False)],
    )
    logo_uri = models.URLField(
        default="",
        blank=True,
        help_text="If provided, return this URI instead of the stored logo",
    )
    events_bugged = models.BooleanField(
        default=False,
        help_text="Set `True` if token does not send `Transfer` event sometimes (e.g. WETH on minting)",
    )
    spam = models.BooleanField(
        default=False, help_text="Spam and trusted cannot be both True"
    )
    trusted = models.BooleanField(
        default=False, help_text="Spam and trusted cannot be both True"
    )
    copy_price = EthereumAddressBinaryField(
        null=True, blank=True, help_text="If provided, copy the price from the token"
    )

    class Meta:
        indexes = [
            models.Index(
                name="token_events_bugged_idx",
                fields=["events_bugged"],
                condition=Q(events_bugged=True),
            ),
            models.Index(
                name="token_spam_idx", fields=["spam"], condition=Q(spam=True)
            ),
            models.Index(
                name="token_trusted_idx", fields=["trusted"], condition=Q(trusted=True)
            ),
        ]

    def __str__(self):
        spam_text = "SPAM " if self.spam else ""
        if self.decimals is None:
            return f"{spam_text}ERC721 - {self.name} - {self.address}"
        else:
            return f"{spam_text}ERC20 - {self.name} - {self.address}"

    def clean(self):
        if self.trusted and self.spam:
            raise ValidationError("Spam and trusted cannot be both `True`")

    def is_erc20(self):
        return self.decimals is not None

    def is_erc721(self):
        return not self.is_erc20()

    def set_trusted(self) -> None:
        self.trusted = True
        return self.save(update_fields=["trusted"])

    def set_spam(self) -> None:
        self.spam = True
        return self.save(update_fields=["spam"])

    def get_full_logo_uri(self) -> str:
        if self.logo:
            return self.logo.url

        if self.logo_uri:
            return self.logo_uri

        if settings.AWS_S3_PUBLIC_URL:
            return urljoin(
                settings.AWS_S3_PUBLIC_URL,
                get_token_logo_path(
                    self, self.address + settings.TOKENS_LOGO_EXTENSION
                ),
            )

        # Old behaviour
        return urljoin(
            settings.TOKENS_LOGO_BASE_URI,
            get_token_logo_path(self, self.address + settings.TOKENS_LOGO_EXTENSION),
        )

    def get_price_address(self) -> ChecksumAddress:
        """
        :return: Address to use to retrieve the token price
        """
        return self.copy_price or self.address


class TokenNotValid(models.Model):
    """
    Stores information about tokens not valid (missing name or symbol, for example), so they are not requested
    again to the RPC
    """

    address = EthereumAddressBinaryField(primary_key=True)


class TokenListToken(TypedDict):
    symbol: str
    name: str
    address: str  # Can be an ENS address
    decimals: int
    chainId: int
    logoURI: str
    tags: list[str] | None


class TokenList(models.Model):
    """References an external token list that should be ingested into the service."""

    url = models.URLField(unique=True)
    description = models.CharField(max_length=200)

    auth_type = models.CharField(
        max_length=20,
        choices=[
            ("none", "None"),
            ("api_key", "API Key (Header)"),
            ("bearer", "Bearer Token"),
            ("basic", "Basic Auth"),
            ("query", "Query Param"),
        ],
        default="none",
    )

    auth_key = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Authentication key name. Usage depends on auth_type: "
            "For 'api_key': header name (e.g., 'x-api-key'). "
            "For 'bearer': header name (e.g., 'Authorization'). "
            "For 'query': query parameter name (e.g., 'api_key'). "
            "For 'basic': leave empty. "
            "For 'none': leave empty."
        ),
    )

    auth_value = models.TextField(
        blank=True,
        help_text=(
            "Authentication credentials. Usage depends on auth_type: "
            "For 'api_key': the API key value. "
            "For 'bearer': the bearer token value (without 'Bearer ' prefix). "
            "For 'basic': the full 'Basic <base64>' value (e.g., 'Basic dXNlcjpwYXNz'). "
            "For 'query': the query parameter value. "
            "For 'none': leave empty."
        ),
    )

    def __str__(self):
        return f"{self.description} token list"

    def clean(self):
        super().clean()

        if self.auth_type == "none":
            if self.auth_key or self.auth_value:
                raise ValidationError(
                    "auth_key and auth_value must be empty when auth_type is 'none'"
                )

        elif self.auth_type in {"bearer", "api_key", "query"}:
            if not self.auth_key:
                raise ValidationError(
                    {"auth_key": "auth_key is required for this auth_type"}
                )
            if not self.auth_value:
                raise ValidationError(
                    {"auth_value": "auth_value is required for this auth_type"}
                )

        elif self.auth_type == "basic":
            if not self.auth_value:
                raise ValidationError(
                    {"auth_value": "auth_value is required for basic auth"}
                )

    def _build_authenticated_request(self) -> tuple[str, dict]:
        """
        Builds the URL and headers with authentication based on the configured auth_type.
        Supports bearer tokens, API keys (header-based), basic auth, and query parameters.

        :return: Tuple of (authenticated_url, headers_dict)
        """
        url = self.url
        headers: dict[str, str] = {}

        if self.auth_type == "bearer":
            header_name = self.auth_key if self.auth_key else "Authorization"
            headers[header_name] = f"Bearer {self.auth_value}"

        elif self.auth_type == "api_key":
            headers[self.auth_key] = self.auth_value

        elif self.auth_type == "basic":
            headers["Authorization"] = self.auth_value

        elif self.auth_type == "query":
            parsed = urlparse(url)
            query = dict(parse_qsl(parsed.query))
            query[self.auth_key] = self.auth_value

            url = urlunparse(parsed._replace(query=urlencode(query)))

        return url, headers

    def get_tokens(self) -> list[TokenListToken]:
        try:
            url, headers = self._build_authenticated_request()
            response = requests.get(url, headers=headers, timeout=5)
            if response.ok:
                tokens = response.json().get("tokens", [])
                if not tokens:
                    logger.error("Empty token list from %s", self.url)
                return tokens
            else:
                logger.error(
                    "%d - %s when retrieving token list %s",
                    response.status_code,
                    response.content,
                    self.url,
                )
                raise TokenListRetrievalException(
                    f"{response.status_code} when retrieving token list {self.url}"
                )
        except OSError as exc:
            logger.error("Problem retrieving token list %s", self.url)
            raise TokenListRetrievalException(
                f"Problem retrieving token list {self.url}"
            ) from exc
        except JSONDecodeError as exc:
            logger.error("Invalid JSON from token list %s", self.url)
            raise TokenListRetrievalException(
                f"Invalid JSON from token list {self.url}"
            ) from exc
