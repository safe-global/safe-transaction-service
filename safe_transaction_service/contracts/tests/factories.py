import factory
from eth_account import Account
from factory.django import DjangoModelFactory

from gnosis.eth.tests.clients.mocks import sourcify_safe_metadata

from ..models import Contract, ContractAbi


class ContractAbiFactory(DjangoModelFactory):
    class Meta:
        model = ContractAbi

    # Prevent duplicated abis
    abi = factory.Sequence(
        lambda n: sourcify_safe_metadata["output"]["abi"]
        + [
            {
                "anonymous": False,
                "inputs": [
                    {
                        "indexed": False,
                        "internalType": "address",
                        "name": "owner",
                        "type": "address",
                    }
                ],
                "name": f"EventToPreventUniqueError-{n}",
                "type": "event",
            }
        ]
    )
    description = "Gnosis Safe v1.2.0 ABI"
    relevance = 1


class ContractFactory(DjangoModelFactory):
    class Meta:
        model = Contract

    address = factory.LazyFunction(lambda: Account.create().address)
    name = factory.Faker("cryptocurrency_name")
    display_name = ""
    logo = factory.django.ImageField(color="green")
    contract_abi = factory.SubFactory(ContractAbiFactory)
    trusted_for_delegate_call = False
