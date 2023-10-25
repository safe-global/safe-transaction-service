from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from gnosis.eth import EthereumClient

from safe_transaction_service.contracts.models import Contract
from safe_transaction_service.contracts.tests.factories import ContractFactory


class TestCommands(TestCase):
    def test_index_contracts_with_metadata(self):
        command = "index_contracts_with_metadata"

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn(
            "Calling `create_missing_contracts_with_metadata_task` task", buf.getvalue()
        )
        self.assertIn("Task was sent", buf.getvalue())

        buf = StringIO()
        call_command(command, "--reindex", "--sync", stdout=buf)
        self.assertIn(
            "Calling `reindex_contracts_without_metadata_task` task", buf.getvalue()
        )
        self.assertIn("Processing finished", buf.getvalue())

    @patch.object(EthereumClient, "get_chain_id", autospec=True, return_value=137)
    def test_update_safe_contracts_logo(self, mock_chain_id):
        command = "update_safe_contracts_logo"
        buf = StringIO()
        random_contract = ContractFactory()
        previous_random_contract_logo = random_contract.logo.read()
        multisend_address = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
        multisend_contract = ContractFactory(
            address=multisend_address, name="GnosisMultisend"
        )
        multisend_contract_logo = multisend_contract.logo.read()

        call_command(command, stdout=buf)
        current_multisend_contract = Contract.objects.get(address=multisend_address)
        # Previous created contracts logo should be updated
        self.assertNotEqual(
            current_multisend_contract.logo.read(), multisend_contract_logo
        )

        # Previous created contracts name and display name should keep unchanged
        self.assertEqual(multisend_contract.name, current_multisend_contract.name)
        self.assertEqual(
            multisend_contract.display_name, current_multisend_contract.display_name
        )

        # No safe contract logos should keep unchanged
        current_no_safe_contract_logo: bytes = Contract.objects.get(
            address=random_contract.address
        ).logo.read()
        self.assertEqual(current_no_safe_contract_logo, previous_random_contract_logo)

        # Missing safe addresses should be added
        self.assertEqual(Contract.objects.count(), 10)

        # Contract name and display name should be correctly generated
        safe_l2_130_address = "0x3E5c63644E683549055b9Be8653de26E0B4CD36E"
        contract = Contract.objects.get(address=safe_l2_130_address)
        self.assertEqual(contract.name, "GnosisSafeL2")
        self.assertEqual(contract.display_name, "SafeL2 1.3.0")

        safe_multisend_130_address = "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761"
        contract = Contract.objects.get(address=safe_multisend_130_address)
        self.assertEqual(contract.name, "MultiSend")
        self.assertEqual(contract.display_name, "Safe: MultiSend 1.3.0")

        # Force to update contract names should update the name and display name of the contract
        call_command(
            command,
            "--force-update-contract-names",
            stdout=buf,
        )
        contract = Contract.objects.get(address=multisend_address)
        self.assertEqual(contract.name, "MultiSendCallOnly")
        self.assertEqual(contract.display_name, "Safe: MultiSendCallOnly 1.3.0")
