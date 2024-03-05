import json
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.fields.files import ImageFieldFile
from django.db.transaction import atomic
from django.test import TestCase

from eth_account import Account

from gnosis.eth.ethereum_client import EthereumNetwork
from gnosis.eth.tests.clients.mocks import sourcify_safe_metadata

from ..models import Contract, ContractAbi, validate_abi
from .factories import ContractAbiFactory, ContractFactory
from .mocks.contract_metadata_mocks import (
    etherscan_metadata_mock,
    sourcify_metadata_mock,
)


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
    def test_contract_create_from_metadata(self):
        safe_contract_address = "0x6851D6fDFAfD08c0295C392436245E5bc78B0185"
        contract = Contract.objects.create_from_metadata(
            safe_contract_address, sourcify_metadata_mock
        )
        self.assertEqual(contract.name, "Sourcify Uxio Contract")
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 2)

        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_metadata(
                    safe_contract_address, sourcify_metadata_mock
                )

        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_metadata(
                    safe_contract_address, etherscan_metadata_mock
                )

        contract.delete()
        contract = Contract.objects.create_from_metadata(
            safe_contract_address, etherscan_metadata_mock
        )
        self.assertEqual(contract.name, "Etherscan Uxio Contract")
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 2)

        contract_metadata = None
        new_safe_contract_address = Account.create().address
        contract_without_metadata = Contract.objects.create_from_metadata(
            new_safe_contract_address, contract_metadata
        )
        self.assertEqual(contract_without_metadata.name, "")
        self.assertIsNone(contract_without_metadata.contract_abi)

    def test_fix_missing_logos(self):
        self.assertEqual(Contract.objects.fix_missing_logos(), 0)
        contract_name = "test-contract"
        contract_display_name = "awesome-contract"
        contract = ContractFactory(logo="", name=contract_name, display_name="")
        contract.display_name = contract_display_name
        contract.save()
        self.assertIn("without logo", str(contract))
        self.assertEqual(Contract.objects.with_logo().count(), 0)
        self.assertEqual(Contract.objects.without_logo().count(), 1)
        self.assertEqual(contract.logo, "")
        self.assertEqual(Contract.objects.fix_missing_logos(), 0)
        with mock.patch.object(ImageFieldFile, "size", return_value=1):
            self.assertEqual(Contract.objects.fix_missing_logos(), 1)

        contract.refresh_from_db()
        self.assertIn("with logo", str(contract))
        self.assertIn(f"{contract.address}.png", contract.logo.name)
        self.assertEqual(Contract.objects.with_logo().count(), 1)
        self.assertEqual(Contract.objects.without_logo().count(), 0)

    def test_update_from_metadata(self):
        contract_name = "Hello"
        contract = Contract.objects.create(
            address="0xaE32496491b53841efb51829d6f886387708F99B",
            name=contract_name,
            contract_abi=None,
        )
        network = EthereumNetwork.MAINNET
        self.assertIsNone(contract.contract_abi)
        self.assertEqual(ContractAbi.objects.count(), 0)
        self.assertTrue(contract.update_from_metadata(sourcify_metadata_mock))
        # Remove contract_abi description and sync again to check that's filled
        contract.contract_abi.description = ""
        contract.contract_abi.save()
        self.assertTrue(contract.update_from_metadata(sourcify_metadata_mock))
        self.assertIsNotNone(contract.contract_abi)
        self.assertEqual(contract.name, contract_name)
        contract_abi = contract.contract_abi
        self.assertEqual(
            contract_abi.description,
            sourcify_metadata_mock.name,
        )
        self.assertEqual(contract_abi.abi, sourcify_metadata_mock.abi)

        self.assertTrue(contract.update_from_metadata(etherscan_metadata_mock))
        self.assertEqual(ContractAbi.objects.count(), 2)  # A new ABI was inserted
        self.assertNotEqual(
            contract.contract_abi, contract_abi
        )  # Contract_abi was changed
        contract_abi.refresh_from_db()
        self.assertEqual(
            contract_abi.description,
            sourcify_metadata_mock.name,
        )  # Description should not change

        self.assertFalse(contract.update_from_metadata(None))

    def test_without_metadata(self):
        ContractFactory(name="aloha", contract_abi=None)
        ContractFactory(name="")
        self.assertEqual(Contract.objects.without_metadata().count(), 2)
        ContractFactory()
        self.assertEqual(Contract.objects.without_metadata().count(), 2)

    def test_validate_abi(self):
        with self.assertRaises(ValidationError):
            validate_abi([])

        with self.assertRaises(ValidationError):
            validate_abi([1])

        with self.assertRaises(ValidationError):
            validate_abi(["a"])

        validate_abi(sourcify_safe_metadata["output"]["abi"])
