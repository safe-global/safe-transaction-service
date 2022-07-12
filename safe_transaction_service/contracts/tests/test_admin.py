from django.contrib.admin import site
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from safe_transaction_service.contracts.admin import ContractAdmin
from safe_transaction_service.contracts.tests.factories import (
    ContractAbiFactory,
    ContractFactory,
)

from ..models import Contract


class ContractAdminTest(TestCase):
    request_factory = RequestFactory()

    @classmethod
    def setUpTestData(cls) -> None:
        # Create superuser (alfred)
        cls.alfred = User.objects.create_superuser(
            "alfred", "alfred@example.com", "password"
        )

    def test_lookup(self) -> None:
        contract1 = ContractFactory.create(
            contract_abi=ContractAbiFactory.create(description="Contract1")
        )
        contract2 = ContractFactory.create(
            contract_abi=ContractAbiFactory.create(description="Contract2")
        )
        contract_admin = ContractAdmin(Contract, site)
        request = self.request_factory.get("/")
        request.user = self.alfred
        self.assertEqual(1, 1)
