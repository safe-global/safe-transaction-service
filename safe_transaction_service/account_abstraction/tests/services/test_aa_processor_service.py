from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from gnosis.eth import EthereumClient

from safe_transaction_service.account_abstraction.services import (
    get_aa_processor_service,
)
from safe_transaction_service.history.tests import factories as history_factories
from safe_transaction_service.history.utils import clean_receipt_log

from ...models import SafeOperation as SafeOperationModel
from ...models import SafeOperationConfirmation as SafeOperationConfirmationModel
from ...models import UserOperation as UserOperationModel
from ...models import UserOperationReceipt as UserOperationReceiptModel
from ..mocks import (
    aa_chain_id,
    aa_expected_safe_operation_hash,
    aa_expected_user_operation_hash,
    aa_safe_address,
    aa_tx_receipt_mock,
)


class TestAaProcessorService(TestCase):

    def setUp(self):
        super().setUp()
        get_aa_processor_service.cache_clear()
        self.aa_processor_service = get_aa_processor_service()

    def tearDown(self):
        super().tearDown()
        get_aa_processor_service.cache_clear()

    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=aa_chain_id,  # Needed for hashes to match
    )
    def test_process_aa_transaction(self, get_chain_id_mock: MagicMock):
        ethereum_tx = history_factories.EthereumTxFactory(
            logs=[clean_receipt_log(log) for log in aa_tx_receipt_mock["logs"]]
        )
        self.aa_processor_service.process_aa_transaction(aa_safe_address, ethereum_tx)

        user_operation_model = UserOperationModel.objects.get()
        safe_operation_model = SafeOperationModel.objects.get()
        user_operation_receipt_model = UserOperationReceiptModel.objects.get()
        user_operation_confirmation_model = SafeOperationConfirmationModel.objects.get()

        self.assertEqual(
            user_operation_model.hash, aa_expected_user_operation_hash.hex()
        )
        self.assertEqual(
            safe_operation_model.hash, aa_expected_safe_operation_hash.hex()
        )
        self.assertEqual(user_operation_receipt_model.deposited, 759940285250436)
        self.assertEqual(
            user_operation_confirmation_model.owner,
            "0x5aC255889882aCd3da2aA939679E3f3d4cea221e",
        )
