from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from gnosis.eth import EthereumClient

from config.settings.base import STATICFILES_DIRS
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

    @patch.object(EthereumClient, "get_chain_id", autospec=True, return_value=1)
    def test_update_safe_contracts_logo(self, mock_chain_id):
        command = "update_safe_contracts_logo"
        buf = StringIO()
        multisend_address = "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761"
        random_contract = ContractFactory()
        previous_random_contract_logo = random_contract.logo.read()
        multisend_contract: bytes = ContractFactory(
            address=multisend_address, name="Custom multisend"
        )

        call_command(
            command, f"--logo-path={STATICFILES_DIRS[0]}/safe/logo.png", stdout=buf
        )
        current_multisend_contract: bytes = Contract.objects.get(
            address=multisend_address
        )
        # Previous created contracts logo should be updated
        self.assertNotEqual(
            current_multisend_contract.logo.read(), multisend_contract.logo.read()
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
        self.assertEqual(Contract.objects.count(), 28)

        # Contract name and display name should be correctly generated
        safe_l2_141_address = "0x29fcB43b46531BcA003ddC8FCB67FFE91900C762"
        contract = Contract.objects.get(address=safe_l2_141_address)
        self.assertEqual(contract.name, "SafeL2")
        self.assertEqual(contract.display_name, "SafeL2 1.4.1")

        safe_multisend_141_address = "0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526"
        contract = Contract.objects.get(address=safe_multisend_141_address)
        self.assertEqual(contract.name, "MultiSend")
        self.assertEqual(contract.display_name, "Safe: MultiSend 1.4.1")
