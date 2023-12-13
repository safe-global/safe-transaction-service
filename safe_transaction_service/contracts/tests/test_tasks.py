import datetime
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes

from safe_transaction_service.history.tests.factories import MultisigTransactionFactory

from ..models import Contract
from ..services.contract_metadata_service import ContractMetadataService
from ..tasks import (
    ContractAction,
    create_missing_contracts_with_metadata_task,
    create_missing_multisend_contracts_with_metadata_task,
    create_or_update_contract_with_metadata_task,
    reindex_contracts_without_metadata_task,
)
from .mocks.contract_metadata_mocks import sourcify_metadata_mock


class TestTasks(TestCase):
    @mock.patch.object(
        ContractMetadataService, "get_contract_metadata", return_value=None
    )
    def test_contract_tasks(self, contract_metadata_service_mock: MagicMock):
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 0)
        [
            MultisigTransactionFactory(
                to=Account.create().address, data=b"12", trusted=True
            )
            for _ in range(2)
        ]
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 2)
        self.assertEqual(Contract.objects.count(), 2)
        self.assertEqual(
            Contract.objects.filter(contract_abi=None).count(), 2
        )  # Contract ABIs were not found
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 0)

        contract_metadata_service_mock.return_value = sourcify_metadata_mock
        multisig_tx = MultisigTransactionFactory(
            to=Account.create().address, data=b"12", trusted=True
        )
        self.assertEqual(create_missing_contracts_with_metadata_task.delay().result, 1)
        self.assertEqual(
            Contract.objects.without_metadata().count(), 2
        )  # Previously inserted contracts were not processed
        contract = Contract.objects.select_related("contract_abi").get(
            address=multisig_tx.to
        )
        self.assertEqual(contract.name, sourcify_metadata_mock.name)
        self.assertEqual(contract.contract_abi.abi, sourcify_metadata_mock.abi)
        contract_abi_id = contract.contract_abi_id

        # Reindex all the contracts, they should have the same abi
        self.assertEqual(reindex_contracts_without_metadata_task.delay().result, 2)
        self.assertEqual(
            Contract.objects.filter(contract_abi_id=contract_abi_id).count(), 3
        )

    def test_create_missing_multisend_contracts_with_metadata_task(self):
        self.assertEqual(
            create_missing_multisend_contracts_with_metadata_task.delay().result, 0
        )
        [
            MultisigTransactionFactory(to=Account.create().address, data=b"12")
            for _ in range(2)
        ]
        self.assertEqual(
            create_missing_multisend_contracts_with_metadata_task.delay().result, 0
        )

        # 2 Multisend transactions 1 day in the past
        one_day_ago = timezone.now() - datetime.timedelta(days=1)
        multisig_transactions = [
            MultisigTransactionFactory(
                created=one_day_ago,
                trusted=True,
                to="0x40A2aCCbd92BCA938b02010E17A5b8929b49130D",
                data=HexBytes(
                    "0x8d80ff0a0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000017200cfbfac74c26f8647cbdb8c5caf80bb5b32e4313400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024e71bdf41000000000000000000000000611b13d54f0423bc87abdc113aa9d2512a47273500d7155ccde93ab2a956f26767462c0783535932c3000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a4beaeb388000000000000000000000000611b13d54f0423bc87abdc113aa9d2512a4727350000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008e1bc9bf040000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
                ),
            ),
            MultisigTransactionFactory(
                created=one_day_ago,
                trusted=True,
                to="0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761",
                data=HexBytes("0x12345"),
            ),
        ]

        # Transactions should not be picked as they should be at much 1 day old
        self.assertEqual(
            create_missing_multisend_contracts_with_metadata_task.delay().result, 0
        )

        for multisig_transaction in multisig_transactions:
            multisig_transaction.created = timezone.now()
            multisig_transaction.save(update_fields=["created"])

        # Not valid multisend transaction should not break the indexer
        self.assertEqual(
            create_missing_multisend_contracts_with_metadata_task.delay().result, 2
        )

        self.assertEqual(
            Contract.objects.filter(
                address__in=[
                    "0xCFbFaC74C26F8647cBDb8c5caf80BB5b32E43134",
                    "0xD7155cCDE93AB2A956F26767462C0783535932c3",
                ]
            ).count(),
            2,
        )

        # Try again, nothing should be indexed
        self.assertEqual(
            create_missing_multisend_contracts_with_metadata_task.delay().result, 0
        )

    @mock.patch.object(
        ContractMetadataService,
        "get_contract_metadata",
        return_value=sourcify_metadata_mock,
    )
    def test_create_or_update_contract_with_metadata_task(
        self, contract_metadata_service_mock: MagicMock
    ):
        random_address = Account.create().address

        self.assertFalse(Contract.objects.filter(address=random_address).exists())
        contract_action = create_or_update_contract_with_metadata_task(random_address)
        self.assertEqual(contract_action, ContractAction.CREATED)
        self.assertTrue(Contract.objects.filter(address=random_address).exists())

        # Try with a contract already created
        contract_action = create_or_update_contract_with_metadata_task(random_address)
        self.assertEqual(contract_action, ContractAction.UPDATED)
        self.assertTrue(Contract.objects.filter(address=random_address).exists())

        contract_metadata_service_mock.return_value = None
        contract_action = create_or_update_contract_with_metadata_task(random_address)
        self.assertEqual(contract_action, ContractAction.NOT_MODIFIED)
