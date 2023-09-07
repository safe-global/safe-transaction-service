from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from gnosis.eth import EthereumClient
from gnosis.safe.safe_deployments import safe_deployments

from config.settings.base import STATICFILES_DIRS
from safe_transaction_service.contracts.management.commands.update_safe_contracts_logo import (
    get_deployment_addresses,
)
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

    @patch.object(EthereumClient, "get_chain_id", autospec=True, return_value=5)
    def test_update_safe_contracts_logo(self, mock_chain_id):
        command = "update_safe_contracts_logo"
        buf = StringIO()
        multisend_address = "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761"
        random_contract = ContractFactory()
        previous_random_contract_logo = random_contract.logo.read()
        previous_multisend_logo: bytes = ContractFactory(
            address=multisend_address
        ).logo.read()
        call_command(
            command, f"--logo-path={STATICFILES_DIRS[0]}/safe/logo.png", stdout=buf
        )
        current_multisend_logo: bytes = Contract.objects.get(
            address=multisend_address
        ).logo.read()
        self.assertNotEqual(current_multisend_logo, previous_multisend_logo)
        # No safe contract logos should keep unchanged
        current_no_safe_contract_logo: bytes = Contract.objects.get(
            address=random_contract.address
        ).logo.read()
        self.assertEqual(current_no_safe_contract_logo, previous_random_contract_logo)

    def test_get_deployment_addresses(self):
        expected_result = [
            "0x29fcB43b46531BcA003ddC8FCB67FFE91900C762",
            "0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526",
            "0x9641d764fc13c8B624c04430C7356C1C7C8102e2",
            "0x41675C099F32341bf84BFc5382aF534df5C7461a",
            "0x3d4BA2E0884aa488718476ca2FB8Efc291A46199",
            "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67",
            "0x9b35Af71d77eaf8d7e40252370304687390A1A52",
            "0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99",
            "0xd53cd0aB83D845Ac265BE939c57F53AD838012c9",
        ]

        result = get_deployment_addresses(safe_deployments["1.4.1"], "1")

        self.assertEqual(expected_result, result)
