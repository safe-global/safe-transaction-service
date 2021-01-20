import os
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import JSONField
from django.utils.translation import gettext_lazy as _

from storages.backends.s3boto3 import S3Boto3Storage
from web3._utils.normalizers import normalize_abi

from gnosis.eth.django.models import EthereumAddressField

from safe_transaction_service.contracts.sourcify import Sourcify


def get_file_storage():
    if settings.AWS_CONFIGURED:
        return S3Boto3Storage()
    else:
        return default_storage


def validate_abi(value: Dict[str, Any]):
    try:
        normalize_abi(value)
    except ValueError:
        raise ValidationError(
            _('%(value)s is not a valid Ethereum Contract ABI'),
            params={'value': value},
        )


class ContractAbi(models.Model):
    """
    This model holds contract ABIs. Contract ABIS don't have to be tied to a contract
    (e.g. generic ERC20/721 ABI)
    """
    abi = JSONField(validators=[validate_abi])
    description = models.CharField(max_length=200, blank=True)
    relevance = models.SmallIntegerField(default=100)  # A lower number will indicate more relevance

    def __str__(self):
        return f'ContractABI {self.relevance} - {self.description}'

    def abi_functions(self) -> List[str]:
        return [x['name'] for x in self.abi if x['type'] == 'function']


class ContractManager(models.Manager):
    def create_from_address(self, address: str, network_id: int = 1) -> Optional['Contract']:
        sourcify = Sourcify()
        contract_metadata = sourcify.get_contract_metadata(address, network_id=network_id)
        if contract_metadata:
            if contract_metadata.abi:
                try:
                    contract_abi = ContractAbi.objects.filter(abi=contract_metadata.abi).get()
                except ContractAbi.DoesNotExist:
                    contract_abi = ContractAbi.objects.create(
                        abi=contract_metadata.abi, description=contract_metadata.name
                    )
            else:
                contract_abi = None

            return super().create(
                address=address,
                name=contract_metadata.name,
                contract_abi=contract_abi,
            )


def get_contract_logo_path(instance: 'Contract', filename):
    # file will be uploaded to MEDIA_ROOT/<address>
    _, extension = os.path.splitext(filename)
    return f'contracts/logos/{instance.address}{extension}'  # extension includes '.'


class Contract(models.Model):
    objects = ContractManager()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=200, blank=True, default='')
    display_name = models.CharField(max_length=200, blank=True, default='')
    logo = models.ImageField(null=True, default=None, upload_to=get_contract_logo_path, storage=get_file_storage)
    contract_abi = models.ForeignKey(ContractAbi, on_delete=models.CASCADE, null=True, default=None,
                                     related_name='contracts')

    def __str__(self):
        has_abi = self.contract_abi_id is not None
        logo = ' with logo' if self.logo else ' without logo'
        return f'Contract {self.address} - {self.name} - with abi {has_abi}{logo}'

    def get_main_name(self):
        """
        :return: `display_name` if available, else use scraped `name`
        """
        return self.display_name if self.display_name else self.name
