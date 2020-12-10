from typing import Optional

from django.db import models
from django.db.models import JSONField

from gnosis.eth.django.models import EthereumAddressField

from safe_transaction_service.contracts.sourcify import Sourcify


class ContractAbi(models.Model):
    """
    This model holds contract ABIs. Contract ABIS don't have to be tied to a contract
    (e.g. generic ERC20/721 ABI)
    """
    abi = JSONField()
    description = models.CharField(max_length=200, blank=True)
    relevance = models.SmallIntegerField(default=100)  # A lower number will indicate more relevance


class ContractManager(models.Manager):
    def create_from_address(self, address: str, network_id: int = 1) -> Optional['Contract']:
        sourcify = Sourcify()
        contract_metadata = sourcify.get_contract_metadata(address, network_id=network_id)
        if contract_metadata:
            contract_abi = ContractAbi.objects.create(abi=contract_metadata.abi) if contract_metadata.abi else None
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

