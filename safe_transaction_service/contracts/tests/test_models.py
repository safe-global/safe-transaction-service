# SPDX-License-Identifier: FSL-1.1-MIT
import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.transaction import atomic
from django.test import TestCase

from safe_eth.eth.tests.clients.mocks import sourcify_safe_metadata

from ..models import Contract, ContractAbi, get_contract_logo_path, validate_abi
from .factories import ContractAbiFactory, ContractFactory


class TestContractAbi(TestCase):
    def test_contract_abi_hash(self):
        abi = sourcify_safe_metadata["output"]["abi"]
        contract_abi = ContractAbi.objects.create(abi=abi, description="testing")
        self.assertIsNotNone(contract_abi.abi_hash)
        self.assertGreater(len(str(contract_abi)), 1)

        with self.assertRaisesMessage(IntegrityError, "violates unique constraint"):
            with atomic():
                ContractAbi.objects.create(
                    abi=json.dumps(abi), description="another testing"
                )

        ContractAbi.objects.create(abi={}, description="testing 3")

    def test_contract_abi_save(self):
        contract_abi = ContractAbiFactory()
        abi_hash = contract_abi.abi_hash
        contract_abi.abi = {}
        contract_abi.save(update_fields=["abi"])
        self.assertNotEqual(contract_abi.abi_hash, abi_hash)

        description = "testing"
        # Description will be updated
        ContractAbi(abi={}, description=description).save()
        contract_abi.refresh_from_db()
        self.assertEqual(contract_abi.description, description)


class TestContract(TestCase):
    def test_with_logo_without_logo(self):
        """
        Contracts are split between `with_logo` and `without_logo` by the logo field
        """
        contract = ContractFactory(logo="")
        self.assertIn("without logo", str(contract))
        self.assertEqual(Contract.objects.with_logo().count(), 0)
        self.assertEqual(Contract.objects.without_logo().count(), 1)

        contract.logo.name = get_contract_logo_path(contract, "logo.png")
        contract.save(update_fields=["logo"])
        self.assertIn("with logo", str(contract))
        self.assertEqual(Contract.objects.with_logo().count(), 1)
        self.assertEqual(Contract.objects.without_logo().count(), 0)

    def test_validate_abi(self):
        with self.assertRaises(ValidationError):
            validate_abi([])

        with self.assertRaises(ValidationError):
            validate_abi([1])

        with self.assertRaises(ValidationError):
            validate_abi(["a"])

        validate_abi(sourcify_safe_metadata["output"]["abi"])
