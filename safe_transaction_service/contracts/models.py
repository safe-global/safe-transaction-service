from typing import Any, Dict, List, Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField
from django.utils.translation import gettext_lazy as _

from web3._utils.normalizers import normalize_abi

from gnosis.eth.django.models import EthereumAddressField

from safe_transaction_service.contracts.sourcify import Sourcify


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
            contract_abi = ContractAbi.objects.create(
                abi=contract_metadata.abi, description=contract_metadata.name
            ) if contract_metadata.abi else None

            return super().create(
                address=address,
                name=contract_metadata.name,
                contract_abi=contract_abi,
            )


class Contract(models.Model):
    objects = ContractManager()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=200, blank=True, default='')
    contract_abi = models.ForeignKey(ContractAbi, on_delete=models.CASCADE, null=True, default=None,
                                     related_name='contracts')

    def __str__(self):
        has_abi = self.contract_abi_id is not None
        return f'Contract {self.address} - {self.name} - with abi {has_abi}'
