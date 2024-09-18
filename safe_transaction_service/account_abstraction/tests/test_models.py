from django.test import TestCase

from safe_eth.eth.account_abstraction import UserOperation as UserOperationClass
from safe_eth.eth.tests.mocks.mock_bundler import (
    safe_4337_module_address_mock,
    safe_4337_safe_operation_hash_mock,
    safe_4337_user_operation_hash_mock,
    user_operation_mock,
)
from safe_eth.safe.account_abstraction import SafeOperation as SafeOperationClass

from safe_transaction_service.history.tests import factories as history_factories

from ..models import SafeOperation as SafeOperationModel
from ..models import UserOperation as UserOperationModel
from .factories import SafeOperationConfirmationFactory


class TestModels(TestCase):
    def test_user_operation(self):
        expected_user_operation_hash = safe_4337_user_operation_hash_mock
        expected_user_operation = UserOperationClass.from_bundler_response(
            expected_user_operation_hash.hex(), user_operation_mock["result"]
        )
        expected_safe_operation = SafeOperationClass.from_user_operation(
            expected_user_operation
        )
        expected_safe_operation_hash = safe_4337_safe_operation_hash_mock
        expected_module_address = safe_4337_module_address_mock

        ethereum_tx = history_factories.EthereumTxFactory(
            tx_hash=user_operation_mock["result"]["transactionHash"],
            block__block_hash=user_operation_mock["result"]["blockHash"],
            block__number=int(user_operation_mock["result"]["blockNumber"], 16),
        )
        user_operation_model: UserOperationModel = UserOperationModel.objects.create(
            ethereum_tx=ethereum_tx,
            hash=expected_user_operation_hash,
            sender=expected_user_operation.sender,
            nonce=expected_user_operation.nonce,
            init_code=expected_user_operation.init_code,
            call_data=expected_user_operation.call_data,
            call_gas_limit=expected_user_operation.call_gas_limit,
            verification_gas_limit=expected_user_operation.verification_gas_limit,
            pre_verification_gas=expected_user_operation.pre_verification_gas,
            max_fee_per_gas=expected_user_operation.max_fee_per_gas,
            max_priority_fee_per_gas=expected_user_operation.max_priority_fee_per_gas,
            paymaster=expected_user_operation.paymaster,
            paymaster_data=expected_user_operation.paymaster_data,
            signature=expected_user_operation.signature,
            entry_point=expected_user_operation.entry_point,
        )

        user_operation = user_operation_model.to_user_operation(add_tx_metadata=True)
        self.assertEqual(user_operation.metadata, expected_user_operation.metadata)
        self.assertEqual(user_operation, expected_user_operation)
        self.assertEqual(
            user_operation_model.to_safe_operation(), expected_safe_operation
        )
        self.assertIsNone(user_operation_model.paymaster_and_data)

        safe_operation_model: SafeOperationModel = SafeOperationModel.objects.create(
            hash=expected_safe_operation_hash,
            user_operation=user_operation_model,
            valid_after=expected_safe_operation.valid_after_as_datetime,
            valid_until=expected_safe_operation.valid_until_as_datetime,
            module_address=expected_module_address,
        )

        self.assertEqual(
            safe_operation_model.build_signature(), user_operation.signature[:12]
        )
        SafeOperationConfirmationFactory(
            safe_operation=safe_operation_model,
            signature=user_operation.signature[12:],
        )
        self.assertEqual(
            safe_operation_model.build_signature(),
            user_operation.signature[:12] + expected_safe_operation.signature,
        )
