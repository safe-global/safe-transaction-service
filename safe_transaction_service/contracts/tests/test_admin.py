from django.contrib.admin import site
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from safe_transaction_service.contracts.admin import ContractAdmin
from safe_transaction_service.contracts.tests.factories import (
    ContractAbiFactory,
    ContractFactory,
)

from ..models import Contract


class TestContractAdmin(TestCase):
    request_factory = RequestFactory()

    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = User.objects.create_superuser(
            "alfred", "alfred@example.com", "password"
        )
        cls.contract1 = ContractFactory.create(
            contract_abi=ContractAbiFactory.create(relevance=3), logo=None
        )
        cls.contract2 = ContractFactory.create(contract_abi=None)
        cls.contract3 = ContractFactory.create(
            contract_abi=ContractAbiFactory.create(relevance=4)
        )
        cls.contracts = {cls.contract1, cls.contract2, cls.contract3}

    def setUp(self) -> None:
        self.contract_admin = ContractAdmin(Contract, site)
        return super().setUp()

    def test_lookups(self) -> None:
        request = self.request_factory.get("/")
        request.user = self.superuser

        changelist = self.contract_admin.get_changelist_instance(request)

        filterspec = changelist.get_filters(request)
        expected_choices = [("YES", "Yes"), ("NO", "No")]
        self.assertEqual(filterspec[0][0].lookup_choices, expected_choices)
        self.assertEqual(filterspec[0][1].lookup_choices, expected_choices)

    def test_unfiltered_lookup(self) -> None:
        request = self.request_factory.get("/")
        request.user = self.superuser

        changelist = self.contract_admin.get_changelist_instance(request)

        # Queryset should contain all the contracts (no filter specified)
        self.assertEqual(
            set(changelist.get_queryset(request)),
            self.contracts,
        )

    def test_has_abi_filter_lookup(self) -> None:
        request = self.request_factory.get("/", {"has_abi": "YES"})
        request.user = self.superuser

        changelist = self.contract_admin.get_changelist_instance(request)

        # Queryset should contain contracts with ABI (contract1 and contract3)
        self.assertEqual(
            set(changelist.get_queryset(request)), {self.contract1, self.contract3}
        )

    def test_has_abi_exclusion_filter_lookup(self) -> None:
        request = self.request_factory.get("/", {"has_abi": "NO"})
        request.user = self.superuser

        changelist = self.contract_admin.get_changelist_instance(request)

        # Queryset should contain contracts with ABI (contract1 and contract3)
        self.assertEqual(set(changelist.get_queryset(request)), {self.contract2})

    def test_has_logo_filter_lookup(self) -> None:
        request = self.request_factory.get("/", {"has_logo": "YES"})
        request.user = self.superuser

        changelist = self.contract_admin.get_changelist_instance(request)

        # Queryset should contain contracts with logo (contract2 and contract3)
        self.assertEqual(
            set(changelist.get_queryset(request)), {self.contract2, self.contract3}
        )

    def test_get_contracts_abi_relevance(self) -> None:
        expected_relevances = map(
            lambda i: None if (i.contract_abi is None) else i.contract_abi.relevance,
            self.contracts,
        )

        relevances = map(lambda c: self.contract_admin.abi_relevance(c), self.contracts)
        self.assertEqual(set(expected_relevances), set(relevances))
