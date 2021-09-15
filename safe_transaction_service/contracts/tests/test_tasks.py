from unittest import mock

from django.test import TestCase

from eth_account import Account

from gnosis.eth.clients import Sourcify
from gnosis.eth.tests.clients.mocks import sourcify_safe_metadata

from safe_transaction_service.history.tests.factories import \
    MultisigTransactionFactory

from ..models import Contract
from ..tasks import (create_missing_contracts_with_metadata_task,
                     reindex_contracts_without_metadata_task)


class TestTasks(TestCase):
    def test_contract_tasks(self):
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 0)
        [MultisigTransactionFactory(to=Account.create().address, data=b'12') for _ in range(2)]
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 2)
        self.assertEqual(Contract.objects.count(), 2)
        self.assertEqual(Contract.objects.filter(contract_abi=None).count(), 2)  # Contract ABIs were not found
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 0)

        with mock.patch.object(Sourcify, '_do_request', autospec=True, return_value=sourcify_safe_metadata):
            multisig_tx = MultisigTransactionFactory(to=Account.create().address, data=b'12')
            contract_metadata = Sourcify().get_contract_metadata(multisig_tx.to)
            self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 1)
            self.assertEqual(Contract.objects.without_metadata().count(),
                             2)  # Previously inserted contracts were not processed
            contract = Contract.objects.select_related('contract_abi').get(address=multisig_tx.to)
            self.assertEqual(contract.name, contract_metadata.name)
            self.assertEqual(contract.contract_abi.abi, contract_metadata.abi)
            contract_abi_id = contract.contract_abi_id

            # Reindex all the contracts, they should have the same abi
            self.assertEqual(reindex_contracts_without_metadata_task(), 2)
            self.assertEqual(Contract.objects.filter(contract_abi_id=contract_abi_id).count(), 3)
