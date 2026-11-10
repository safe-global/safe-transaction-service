# SPDX-License-Identifier: FSL-1.1-MIT
import json
import operator
import os
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import JSONField, Q
from django.utils.translation import gettext_lazy as _

from cachetools import TTLCache, cachedmethod
from imagekit.models import ProcessedImageField
from pilkit.processors import Resize
from safe_eth.eth.django.models import EthereumAddressBinaryField, Keccak256Field
from safe_eth.eth.utils import fast_keccak
from web3._utils.normalizers import normalize_abi


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


def validate_abi(value: dict[str, Any]):
    try:
        if not value:
            raise ValueError("Empty ABI not allowed")
        normalize_abi(value)
    except ValueError as exc:
        raise ValidationError(
            _("%(value)s is not a valid Ethereum Contract ABI: %(reason)s"),
            params={"value": value, "reason": str(exc)},
        ) from exc


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

    def abi_functions(self) -> list[str]:
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


class ContractQuerySet(models.QuerySet):
    cache_trusted_addresses_for_delegate_call = TTLCache(
        maxsize=2048, ttl=60 * 5
    )  # 5 minutes of caching
    no_logo_query = Q(logo=None) | Q(logo="")

    def with_logo(self):
        return self.exclude(self.no_logo_query)

    def without_logo(self):
        return self.filter(self.no_logo_query)

    def trusted_for_delegate_call(self):
        return self.filter(trusted_for_delegate_call=True)

    def trusted_addresses_for_delegate_call(self):
        return self._cached_trusted_addresses_for_delegate_call()

    @cachedmethod(
        cache=operator.attrgetter("cache_trusted_addresses_for_delegate_call")
    )
    def _cached_trusted_addresses_for_delegate_call(self):
        return self.trusted_for_delegate_call().values_list("address", flat=True)


class Contract(models.Model):
    """Tracks known contract addresses with optional ABI and branding metadata."""

    objects = ContractQuerySet.as_manager()
    address = EthereumAddressBinaryField(primary_key=True)
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
