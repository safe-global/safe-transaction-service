from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account
from safe_eth.eth import EthereumClient
from safe_eth.eth.account_abstraction import BundlerClient
from safe_eth.eth.account_abstraction import UserOperation as UserOperationClass
from safe_eth.eth.account_abstraction import (
    UserOperationReceipt as UserOperationReceiptClass,
)
from safe_eth.eth.tests.mocks.mock_bundler import (
    safe_4337_user_operation_hash_mock,
    user_operation_mock,
    user_operation_receipt_mock,
    user_operation_v07_hash,
    user_operation_v07_mock,
)

from safe_transaction_service.account_abstraction.services import (
    get_aa_processor_service,
)
from safe_transaction_service.history.tests import factories as history_factories
from safe_transaction_service.history.utils import clean_receipt_log

from ...models import SafeOperation as SafeOperationModel
from ...models import SafeOperationConfirmation as SafeOperationConfirmationModel
from ...models import UserOperation as UserOperationModel
from ...models import UserOperationReceipt as UserOperationReceiptModel
from ...services.aa_processor_service import (
    UserOperationNotSupportedException,
    UserOperationReceiptNotFoundException,
)
from ...utils import get_bundler_client
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
        get_bundler_client.cache_clear()
        get_aa_processor_service.cache_clear()
        with self.settings(ETHEREUM_4337_BUNDLER_URL="https://localhost"):
            # Bundler must be defined so it's initialized and it can be mocked
            self.aa_processor_service = get_aa_processor_service()
            self.assertIsNotNone(self.aa_processor_service.bundler_client)

    def tearDown(self):
        super().tearDown()
        get_bundler_client.cache_clear()
        get_aa_processor_service.cache_clear()

    @mock.patch.object(
        BundlerClient,
        "get_user_operation_receipt",
        autospec=True,
        return_value=UserOperationReceiptClass.from_bundler_response(
            user_operation_receipt_mock["result"]
        ),
    )
    @mock.patch.object(
        BundlerClient,
        "get_user_operation_by_hash",
        autospec=True,
        return_value=UserOperationClass.from_bundler_response(
            safe_4337_user_operation_hash_mock.hex(), user_operation_mock["result"]
        ),
    )
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=aa_chain_id,  # Needed for hashes to match
    )
    def test_process_aa_transaction(
        self,
        get_chain_id_mock: MagicMock,
        get_user_operation_by_hash_mock: MagicMock,
        get_user_operation_receipt_mock: MagicMock,
    ):
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

        get_user_operation_receipt_mock.return_value = None
        with self.assertRaisesMessage(
            UserOperationReceiptNotFoundException,
            f"Cannot find receipt for user-operation={user_operation_model.hash}",
        ):
            self.aa_processor_service.index_user_operation_receipt(user_operation_model)

    @mock.patch.object(
        BundlerClient,
        "get_user_operation_receipt",
        autospec=True,
        return_value=UserOperationReceiptClass.from_bundler_response(
            user_operation_receipt_mock["result"]
        ),
    )
    @mock.patch.object(
        BundlerClient,
        "get_user_operation_by_hash",
        autospec=True,
        return_value=UserOperationClass.from_bundler_response(
            user_operation_v07_hash.hex(), user_operation_v07_mock["result"]
        ),
    )
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=aa_chain_id,  # Needed for hashes to match
    )
    def test_process_aa_transaction_entrypoint_V07(
        self,
        get_chain_id_mock: MagicMock,
        get_user_operation_by_hash_mock: MagicMock,
        get_user_operation_receipt_mock: MagicMock,
    ):
        """
        Entrypoint v0.7.0 endpoints should be ignored
        """
        ethereum_tx = history_factories.EthereumTxFactory(
            logs=[clean_receipt_log(log) for log in aa_tx_receipt_mock["logs"]]
        )
        with self.assertRaisesMessage(
            UserOperationNotSupportedException, "for EntryPoint v0.7.0 is not supported"
        ):
            self.aa_processor_service.index_user_operation(
                Account.create().address,  # Not relevant
                user_operation_v07_hash,
                ethereum_tx,
            )

        self.aa_processor_service.process_aa_transaction(aa_safe_address, ethereum_tx)
        self.assertEqual(UserOperationModel.objects.count(), 0)
        self.assertEqual(SafeOperationModel.objects.count(), 0)
        self.assertEqual(UserOperationReceiptModel.objects.count(), 0)
        self.assertEqual(SafeOperationConfirmationModel.objects.count(), 0)
