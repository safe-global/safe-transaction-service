import json
import operator
import os
from logging import getLogger
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import JSONField, Q
from django.utils.translation import gettext_lazy as _

from botocore.exceptions import ClientError
from cachetools import TTLCache, cachedmethod
from imagekit.models import ProcessedImageField
from pilkit.processors import Resize
from web3._utils.normalizers import normalize_abi
from web3.contract import Contract

from gnosis.eth.clients import (
    BlockscoutClient,
    BlockScoutConfigurationProblem,
    EtherscanClient,
    EtherscanClientConfigurationProblem,
    Sourcify,
)
from gnosis.eth.django.models import EthereumAddressV2Field, Keccak256Field
from gnosis.eth.ethereum_client import EthereumClientProvider, EthereumNetwork
from gnosis.eth.utils import fast_keccak

logger = getLogger(__name__)


def get_contract_logo_path(instance: "Contract", filename):
    # file will be uploaded to MEDIA_ROOT/<address>
    _, extension = os.path.splitext(filename)
    return f"contracts/logos/{instance.address}{extension}"  # extension includes '.'


def get_file_storage():
    if settings.AWS_CONFIGURED:
        from django_s3_storage.storage import S3Storage

        return S3Storage()
    else:
        return default_storage


def validate_abi(value: Dict[str, Any]):
    try:
        if not value:
            raise ValueError("Empty ABI not allowed")
        normalize_abi(value)
    except ValueError as exc:
        raise ValidationError(
            _("%(value)s is not a valid Ethereum Contract ABI: %(reason)s"),
            params={"value": value, "reason": str(exc)},
        )


class ContractAbi(models.Model):
    """
    This model holds contract ABIs. Contract ABIS don't have to be tied to a contract
    (e.g. generic ERC20/721 ABI)
    """

    abi = JSONField(validators=[validate_abi])
    description = models.CharField(max_length=200, blank=True)
    relevance = models.SmallIntegerField(
        default=100
    )  # A lower number will indicate more relevance
    abi_hash = Keccak256Field(default=None, blank=True, null=True, unique=True)

    def __str__(self):
        return f"ContractABI {self.relevance} - {self.description}"

    def abi_functions(self) -> List[str]:
        return [x["name"] for x in self.abi if x["type"] == "function"]

    def save(self, *args, **kwargs) -> None:
        if update_fields := kwargs.get("update_fields"):
            if "abi_hash" not in update_fields:
                update_fields.append("abi_hash")
        if isinstance(self.abi, str):
            self.abi = json.loads(self.abi)
        self.abi_hash = fast_keccak(
            json.dumps(self.abi, separators=(",", ":")).encode()
        )
        try:
            # ABI already exists, overwrite
            contract_abi = self.__class__.objects.get(abi_hash=self.abi_hash)
            self.id = contract_abi.id
            self.description = self.description or contract_abi.description
        except self.__class__.DoesNotExist:
            pass
        return super().save(*args, **kwargs)


class ContractManager(models.Manager):
    def create_from_address(
        self, address: str, network: Optional[EthereumNetwork] = None
    ) -> Contract:
        """
        Create contract and try to fetch information from APIs

        :param address:
        :param network:
        :return: Contract instance populated with all the information found
        """
        contract = super().create(address=address)
        contract.sync_abi_from_api(network=network)
        return contract

    def fix_missing_logos(self) -> int:
        """
        Syncs contracts with empty logos with files that exist on S3 and match the address

        :return: Number of synced logos
        """
        synced_logos = 0
        for contract in self.without_logo():
            filename = get_contract_logo_path(contract, f"{contract.address}.png")
            contract.logo.name = filename
            try:
                if contract.logo.size:
                    synced_logos += 1
                    contract.save(update_fields=["logo"])
                    logger.info("Found logo on url %s", contract.logo.url)
            except (ClientError, FileNotFoundError):  # Depending on aws or filesystem
                logger.error("Error retrieving url %s", contract.logo.url)
        return synced_logos


class ContractQuerySet(models.QuerySet):
    cache_trusted_addresses_for_delegate_call = TTLCache(
        maxsize=2048, ttl=60 * 5
    )  # 5 minutes of caching
    no_logo_query = Q(logo=None) | Q(logo="")

    def with_logo(self):
        return self.exclude(self.no_logo_query)

    def without_logo(self):
        return self.filter(self.no_logo_query)

    def without_metadata(self):
        return self.filter(Q(contract_abi=None) | Q(name=""))

    def trusted_for_delegate_call(self):
        return self.filter(trusted_for_delegate_call=True)

    @cachedmethod(
        cache=operator.attrgetter("cache_trusted_addresses_for_delegate_call")
    )
    def trusted_addresses_for_delegate_call(self):
        return self.trusted_for_delegate_call().values_list("address", flat=True)


class Contract(models.Model):  # Known contract addresses by the service
    objects = ContractManager.from_queryset(ContractQuerySet)()
    address = EthereumAddressV2Field(primary_key=True)
    name = models.CharField(max_length=200, blank=True, default="")
    display_name = models.CharField(max_length=200, blank=True, default="")
    logo = ProcessedImageField(
        blank=True,
        default="",
        upload_to=get_contract_logo_path,
        storage=get_file_storage,
        format="PNG",
        processors=[Resize(256, 256, upscale=False)],
    )
    contract_abi = models.ForeignKey(
        ContractAbi,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        blank=True,
        related_name="contracts",
    )
    # Trusted for doing delegate calls, as it's very dangerous doing delegate calls to other contracts
    trusted_for_delegate_call = models.BooleanField(default=False)

    def __str__(self):
        has_abi = self.contract_abi_id is not None
        logo = " with logo" if self.logo else " without logo"
        return f"Contract {self.address} - {self.name} - with abi {has_abi}{logo}"

    def sync_abi_from_api(self, network: Optional[EthereumNetwork] = None) -> bool:
        """
        Sync ABI from Sourcify, then from Etherscan and Blockscout if available

        :param network: Can be provided to save requests to the node
        :return: True if updated, False otherwise
        """
        ethereum_client = EthereumClientProvider()
        network = network or ethereum_client.get_network()
        sourcify = Sourcify(network)

        try:
            etherscan_client = EtherscanClient(
                network, api_key=settings.ETHERSCAN_API_KEY
            )
        except EtherscanClientConfigurationProblem:
            logger.info(
                "Etherscan client is not available for current network %s", network
            )
            etherscan_client = None

        try:
            blockscout_client = BlockscoutClient(network)
        except BlockScoutConfigurationProblem:
            logger.info(
                "Blockscout client is not available for current network %s", network
            )
            blockscout_client = None

        contract_abi: Optional[ContractAbi] = None
        for client in (sourcify, etherscan_client, blockscout_client):
            if not client:
                continue
            try:
                contract_metadata = client.get_contract_metadata(self.address)
                if contract_metadata:
                    name = contract_metadata.name or ""
                    contract_abi, _ = ContractAbi.objects.get_or_create(
                        abi=contract_metadata.abi, defaults={"description": name}
                    )
                    if name:
                        if not contract_abi.description:
                            contract_abi.description = name
                            contract_abi.save(update_fields=["description"])
                        if not self.name:
                            self.name = name
                    self.contract_abi = contract_abi
                    self.save(update_fields=["name", "contract_abi"])
                    break
            except IOError:
                pass

        return bool(contract_abi)
