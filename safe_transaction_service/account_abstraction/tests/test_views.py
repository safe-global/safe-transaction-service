import logging
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase

from gnosis.eth import EthereumClient
from gnosis.eth.account_abstraction import UserOperation as UserOperationClass
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.tests.mocks.mock_bundler import (
    safe_4337_address,
    safe_4337_chain_id_mock,
    safe_4337_module_address_mock,
    safe_4337_safe_operation_hash_mock,
    safe_4337_user_operation_hash_mock,
    user_operation_mock,
)
from gnosis.safe.account_abstraction import SafeOperation as SafeOperationClass
from gnosis.safe.safe_signature import SafeSignatureEOA
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.utils.utils import datetime_to_str

from .. import models
from . import factories

logger = logging.getLogger(__name__)


class TestAccountAbstractionViews(SafeTestCaseMixin, APITestCase):
    def test_safe_operation_view(self):
        random_safe_operation_hash = (
            "0x8aca9664752dbae36135fd0956c956fc4a370feeac67485b49bcd4b99608ae41"
        )
        response = self.client.get(
            reverse(
                "v1:account_abstraction:safe-operation",
                args=(random_safe_operation_hash,),
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})
        safe_address = Account.create().address
        safe_operation = factories.SafeOperationFactory(
            user_operation__sender=safe_address
        )
        response = self.client.get(
            reverse(
                "v1:account_abstraction:safe-operation", args=(safe_operation.hash,)
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = {
            "created": datetime_to_str(safe_operation.created),
            "modified": datetime_to_str(safe_operation.modified),
            "sender": safe_operation.user_operation.sender,
            "nonce": safe_operation.user_operation.nonce,
            "userOperationHash": safe_operation.user_operation.hash,
            "safeOperationHash": safe_operation.hash,
            "initCode": "0x",  # FIXME Should be None
            "callData": "0x",  # FIXME Should be None
            "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
            "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
            "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
            "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
            "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
            "paymaster": NULL_ADDRESS,
            "paymasterData": "0x",
            "signature": "0x",
            "entryPoint": safe_operation.user_operation.entry_point,
            "validAfter": datetime_to_str(safe_operation.valid_after),
            "validUntil": datetime_to_str(safe_operation.valid_until),
            "moduleAddress": safe_operation.module_address,
            "confirmations": [],
            "preparedSignature": None,
        }
        self.assertDictEqual(
            response.json(),
            expected,
        )

        # Add a confirmation
        safe_operation_confirmation = factories.SafeOperationConfirmationFactory(
            safe_operation=safe_operation
        )
        response = self.client.get(
            reverse(
                "v1:account_abstraction:safe-operation", args=(safe_operation.hash,)
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected["preparedSignature"] = safe_operation_confirmation.signature
        expected["confirmations"] = [
            {
                "created": datetime_to_str(safe_operation_confirmation.created),
                "modified": datetime_to_str(safe_operation_confirmation.modified),
                "owner": safe_operation_confirmation.owner,
                "signature": safe_operation_confirmation.signature,
                "signatureType": "EOA",
            }
        ]
        self.assertDictEqual(response.json(), expected)

    def test_safe_operations_view(self):
        safe_address = Account.create().address

        response = self.client.get(
            reverse(
                "v1:account_abstraction:safe-operations",
                args=(safe_address,),
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )
        safe_operation = factories.SafeOperationFactory(
            user_operation__sender=safe_address
        )
        response = self.client.get(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = {
            "created": datetime_to_str(safe_operation.created),
            "modified": datetime_to_str(safe_operation.modified),
            "sender": safe_operation.user_operation.sender,
            "nonce": safe_operation.user_operation.nonce,
            "userOperationHash": safe_operation.user_operation.hash,
            "safeOperationHash": safe_operation.hash,
            "initCode": "0x",  # FIXME Should be None
            "callData": "0x",  # FIXME Should be None
            "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
            "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
            "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
            "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
            "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
            "paymaster": NULL_ADDRESS,
            "paymasterData": "0x",
            "signature": "0x",
            "entryPoint": safe_operation.user_operation.entry_point,
            "validAfter": datetime_to_str(safe_operation.valid_after),
            "validUntil": datetime_to_str(safe_operation.valid_until),
            "moduleAddress": safe_operation.module_address,
            "confirmations": [],
            "preparedSignature": None,
        }
        self.assertDictEqual(
            response.json(),
            {"count": 1, "next": None, "previous": None, "results": [expected]},
        )

        # Add a confirmation
        safe_operation_confirmation = factories.SafeOperationConfirmationFactory(
            safe_operation=safe_operation
        )
        response = self.client.get(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected["preparedSignature"] = safe_operation_confirmation.signature
        expected["confirmations"] = [
            {
                "created": datetime_to_str(safe_operation_confirmation.created),
                "modified": datetime_to_str(safe_operation_confirmation.modified),
                "owner": safe_operation_confirmation.owner,
                "signature": safe_operation_confirmation.signature,
                "signatureType": "EOA",
            }
        ]
        self.assertDictEqual(
            response.json(),
            {"count": 1, "next": None, "previous": None, "results": [expected]},
        )

    @mock.patch(
        "safe_transaction_service.account_abstraction.serializers.get_safe_owners",
    )
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_safe_operation_create_view(
        self, get_chain_id_mock: MagicMock, get_owners_mock: MagicMock
    ):
        account = Account.create()
        safe_address = safe_4337_address
        user_operation_hash = safe_4337_user_operation_hash_mock

        user_operation = UserOperationClass.from_bundler_response(
            user_operation_hash.hex(), user_operation_mock["result"]
        )

        safe_operation = SafeOperationClass.from_user_operation(user_operation)
        safe_operation_hash = safe_4337_safe_operation_hash_mock

        self.assertEqual(
            safe_operation_hash,
            safe_operation.get_safe_operation_hash(
                safe_4337_chain_id_mock, safe_4337_module_address_mock
            ),
        )

        signature = account.signHash(safe_operation_hash)["signature"].hex()
        get_owners_mock.return_value = []
        data = {
            "nonce": safe_operation.nonce,
            "init_code": user_operation.init_code.hex(),
            "call_data": user_operation.call_data.hex(),
            "call_data_gas_limit": user_operation.call_gas_limit,
            "verification_gas_limit": user_operation.verification_gas_limit,
            "pre_verification_gas": user_operation.pre_verification_gas,
            "max_fee_per_gas": user_operation.max_fee_per_gas,
            "max_priority_fee_per_gas": user_operation.max_priority_fee_per_gas,
            "paymaster": user_operation.paymaster,
            "paymaster_data": user_operation.paymaster_data,
            "signature": signature,
            "entry_point": user_operation.entry_point,
            # Safe Operation fields,
            "valid_after": (
                safe_operation.valid_after if safe_operation.valid_after else None
            ),
            "valid_until": (
                safe_operation.valid_until if safe_operation.valid_until else None
            ),
            "module_address": safe_4337_module_address_mock,
        }
        response = self.client.post(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"Signer={account.address} is not an owner. Current owners=[]. Safe-operation-hash={safe_operation_hash.hex()}",
                        code="invalid",
                    )
                ]
            },
        )

        get_owners_mock.return_value = [account.address]
        # Test not valid signature
        with mock.patch.object(SafeSignatureEOA, "is_valid", return_value=False):
            response = self.client.post(
                reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data,
                {
                    "non_field_errors": [
                        ErrorDetail(
                            string=f'Signature={data["signature"]} for owner={account.address} is not valid',
                            code="invalid",
                        )
                    ]
                },
            )

        response = self.client.post(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(models.UserOperation.objects.count(), 1)
        self.assertEqual(models.SafeOperation.objects.count(), 1)

        # Receipt will only be created when Operation is indexed
        self.assertEqual(models.UserOperationReceipt.objects.count(), 0)
        self.assertEqual(
            models.UserOperation.objects.get().hash, user_operation_hash.hex()
        )
        self.assertEqual(
            models.SafeOperation.objects.get().hash, safe_operation_hash.hex()
        )
