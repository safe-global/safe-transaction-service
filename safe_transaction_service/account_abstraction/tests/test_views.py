import dataclasses
import datetime
import logging
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
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
from gnosis.eth.utils import fast_to_checksum_address
from gnosis.safe.account_abstraction import SafeOperation as SafeOperationClass
from gnosis.safe.proxy_factory import ProxyFactoryV141
from gnosis.safe.safe_signature import SafeSignatureEOA
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.utils.utils import datetime_to_str

from .. import models
from ..serializers import SafeOperationSerializer
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
        self.assertEqual(
            response.json(), {"detail": "No SafeOperation matches the given query."}
        )
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
            "safeOperationHash": safe_operation.hash,
            "userOperation": {
                "sender": safe_operation.user_operation.sender,
                "nonce": safe_operation.user_operation.nonce,
                "userOperationHash": safe_operation.user_operation.hash,
                "ethereumTxHash": safe_operation.user_operation.ethereum_tx_id,
                "initCode": "0x",
                "callData": "0x",
                "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
                "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
                "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
                "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
                "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
                "paymaster": NULL_ADDRESS,
                "paymasterData": "0x",
                "entryPoint": safe_operation.user_operation.entry_point,
                "signature": "0x",
            },
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
        expected["preparedSignature"] = safe_operation_confirmation.signature.hex()
        expected["confirmations"] = [
            {
                "created": datetime_to_str(safe_operation_confirmation.created),
                "modified": datetime_to_str(safe_operation_confirmation.modified),
                "owner": safe_operation_confirmation.owner,
                "signature": safe_operation_confirmation.signature.hex(),
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
            "safeOperationHash": safe_operation.hash,
            "userOperation": {
                "sender": safe_operation.user_operation.sender,
                "nonce": safe_operation.user_operation.nonce,
                "userOperationHash": safe_operation.user_operation.hash,
                "ethereumTxHash": safe_operation.user_operation.ethereum_tx_id,
                "initCode": "0x",
                "callData": "0x",
                "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
                "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
                "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
                "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
                "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
                "paymaster": NULL_ADDRESS,
                "paymasterData": "0x",
                "signature": "0x",
                "entryPoint": safe_operation.user_operation.entry_point,
            },
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
        expected["preparedSignature"] = safe_operation_confirmation.signature.hex()
        expected["confirmations"] = [
            {
                "created": datetime_to_str(safe_operation_confirmation.created),
                "modified": datetime_to_str(safe_operation_confirmation.modified),
                "owner": safe_operation_confirmation.owner,
                "signature": safe_operation_confirmation.signature.hex(),
                "signatureType": "EOA",
            }
        ]
        self.assertDictEqual(
            response.json(),
            {"count": 1, "next": None, "previous": None, "results": [expected]},
        )

    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
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
            "paymaster_and_data": (
                user_operation.paymaster_and_data
                if user_operation.paymaster_and_data
                else None
            ),
            "signature": signature,
            "entry_point": user_operation.entry_point,
            # Safe Operation fields,
            "valid_after": (
                datetime_to_str(safe_operation.valid_after_as_datetime)
                if safe_operation.valid_after
                else None
            ),
            "valid_until": (
                datetime_to_str(safe_operation.valid_until_as_datetime)
                if safe_operation.valid_until
                else None
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
            self.assertDictEqual(
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

        # Fake that Safe contract was already deployed, so `init_code` should not be provided
        with mock.patch.object(EthereumClient, "is_contract", return_value=True):
            response = self.client.post(
                reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.data,
                {
                    "init_code": [
                        ErrorDetail(
                            string="`init_code` must be empty as the contract was already initialized",
                            code="invalid",
                        )
                    ]
                },
            )

        with mock.patch.object(
            ProxyFactoryV141, "calculate_proxy_address", return_value=NULL_ADDRESS
        ):
            response = self.client.post(
                reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.data,
                {
                    "init_code": [
                        ErrorDetail(
                            string=f"Provided safe-address={safe_address} does not match calculated-safe-address={NULL_ADDRESS}",
                            code="invalid",
                        )
                    ]
                },
            )

        # Fake that contract was not deployed and init_code was not provided
        with mock.patch.object(
            EthereumClient, "is_contract", return_value=False
        ) as is_contract_mock:
            data_without_init_code = dict(data)
            data_without_init_code["init_code"] = None
            response = self.client.post(
                reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
                format="json",
                data=data_without_init_code,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.data,
                {
                    "init_code": [
                        ErrorDetail(
                            string="`init_code` was not provided and contract was not initialized",
                            code="invalid",
                        )
                    ]
                },
            )
            is_contract_mock.assert_called_once_with(safe_address)

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

        # Try to create the same transaction
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
                        string=f"SafeOperation with hash={safe_operation_hash.hex()} already exists",
                        code="invalid",
                    )
                ]
            },
        )

        # Insert a SafeOperation with higher nonce, nonce should be too low now
        factories.SafeOperationFactory(
            user_operation__nonce=safe_operation.nonce,
            user_operation__sender=safe_address,
        )
        response = self.client.post(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "nonce": [
                    ErrorDetail(
                        string=f'Nonce={data["nonce"]} too low for safe=0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861',
                        code="invalid",
                    )
                ]
            },
        )

    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_safe_operation_valid_until_create_view(
        self, get_chain_id_mock: MagicMock, get_owners_mock: MagicMock
    ):
        """
        Make sure `valid_until` checks are working
        """

        account = Account.create()
        get_owners_mock.return_value = [account.address]
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
        data = {
            "nonce": safe_operation.nonce,
            "init_code": user_operation.init_code.hex(),
            "call_data": user_operation.call_data.hex(),
            "call_data_gas_limit": user_operation.call_gas_limit,
            "verification_gas_limit": user_operation.verification_gas_limit,
            "pre_verification_gas": user_operation.pre_verification_gas,
            "max_fee_per_gas": user_operation.max_fee_per_gas,
            "max_priority_fee_per_gas": user_operation.max_priority_fee_per_gas,
            "paymaster_and_data": (
                user_operation.paymaster_and_data
                if user_operation.paymaster_and_data
                else None
            ),
            "signature": signature,
            "entry_point": user_operation.entry_point,
            # Safe Operation fields,
            "valid_after": (
                datetime_to_str(safe_operation.valid_after_as_datetime)
                if safe_operation.valid_after
                else None
            ),
            "valid_until": datetime_to_str(timezone.now()),
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
                "valid_until": [
                    ErrorDetail(
                        string="`valid_until` cannot be previous to the current timestamp",
                        code="invalid",
                    )
                ]
            },
        )

        # Set valid_until in the future
        valid_until = timezone.now() + datetime.timedelta(minutes=90)
        data["valid_until"] = datetime_to_str(valid_until)
        new_safe_operation = dataclasses.replace(
            safe_operation, valid_until=int(valid_until.timestamp())
        )
        safe_operation_hash = new_safe_operation.get_safe_operation_hash(
            safe_4337_chain_id_mock, safe_4337_module_address_mock
        )
        data["signature"] = account.signHash(safe_operation_hash)["signature"].hex()
        response = self.client.post(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_safe_operation_paymaster_and_data_create_view(
        self, get_chain_id_mock: MagicMock, get_owners_mock: MagicMock
    ):
        """
        Make sure `valid_until` checks are working
        """

        account = Account.create()
        get_owners_mock.return_value = [account.address]
        safe_address = safe_4337_address
        user_operation_hash = safe_4337_user_operation_hash_mock

        paymaster_address = Account.create().address
        paymaster_and_data = HexBytes(paymaster_address)
        user_operation = dataclasses.replace(
            UserOperationClass.from_bundler_response(
                user_operation_hash.hex(), user_operation_mock["result"]
            ),
            paymaster_and_data=paymaster_and_data,
        )

        safe_operation = SafeOperationClass.from_user_operation(user_operation)
        safe_operation_hash = safe_operation.get_safe_operation_hash(
            safe_4337_chain_id_mock, safe_4337_module_address_mock
        )

        signature = account.signHash(safe_operation_hash)["signature"].hex()
        data = {
            "nonce": safe_operation.nonce,
            "init_code": user_operation.init_code.hex(),
            "call_data": user_operation.call_data.hex(),
            "call_data_gas_limit": user_operation.call_gas_limit,
            "verification_gas_limit": user_operation.verification_gas_limit,
            "pre_verification_gas": user_operation.pre_verification_gas,
            "max_fee_per_gas": user_operation.max_fee_per_gas,
            "max_priority_fee_per_gas": user_operation.max_priority_fee_per_gas,
            "paymaster_and_data": "0x00",
            "signature": signature,
            "entry_point": user_operation.entry_point,
            # Safe Operation fields,
            "valid_after": (
                datetime_to_str(safe_operation.valid_after_as_datetime)
                if safe_operation.valid_after
                else None
            ),
            "valid_until": (
                datetime_to_str(safe_operation.valid_after_as_datetime)
                if safe_operation.valid_after
                else None
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
                "paymaster_and_data": [
                    ErrorDetail(
                        string="`paymaster_and_data` length should be at least 20 bytes",
                        code="invalid",
                    )
                ]
            },
        )

        # Set valid paymaster_and_data
        data["paymaster_and_data"] = paymaster_and_data.hex()
        response = self.client.post(
            reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "paymaster_and_data": [
                    ErrorDetail(
                        string=f"paymaster={paymaster_address} was not found in blockchain",
                        code="invalid",
                    )
                ]
            },
        )

        with mock.patch.object(
            EthereumClient,
            "is_contract",
            side_effect=[False, True, True],
        ) as is_contract_mock:
            response = self.client.post(
                reverse("v1:account_abstraction:safe-operations", args=(safe_address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertListEqual(
                is_contract_mock.call_args_list,
                [
                    mock.call(safe_address),
                    mock.call(fast_to_checksum_address(user_operation.init_code[:20])),
                    mock.call(paymaster_address),
                ],
            )

    def test_user_operation_view(self):
        random_user_operation_hash = (
            "0x8aca9664752dbae36135fd0956c956fc4a370feeac67485b49bcd4b99608ae41"
        )
        response = self.client.get(
            reverse(
                "v1:account_abstraction:user-operation",
                args=(random_user_operation_hash,),
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json(), {"detail": "No UserOperation matches the given query."}
        )
        safe_address = Account.create().address
        safe_operation = factories.SafeOperationFactory(
            user_operation__sender=safe_address
        )
        response = self.client.get(
            reverse(
                "v1:account_abstraction:user-operation",
                args=(safe_operation.user_operation.hash,),
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = {
            "sender": safe_operation.user_operation.sender,
            "nonce": safe_operation.user_operation.nonce,
            "userOperationHash": safe_operation.user_operation.hash,
            "ethereumTxHash": safe_operation.user_operation.ethereum_tx_id,
            "initCode": "0x",
            "callData": "0x",
            "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
            "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
            "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
            "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
            "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
            "paymaster": NULL_ADDRESS,
            "paymasterData": "0x",
            "signature": "0x",
            "entryPoint": safe_operation.user_operation.entry_point,
            "safeOperation": {
                "created": datetime_to_str(safe_operation.created),
                "modified": datetime_to_str(safe_operation.modified),
                "safeOperationHash": safe_operation.hash,
                "validAfter": datetime_to_str(safe_operation.valid_after),
                "validUntil": datetime_to_str(safe_operation.valid_until),
                "moduleAddress": safe_operation.module_address,
                "confirmations": [],
                "preparedSignature": None,
            },
        }
        self.assertDictEqual(
            response.json(),
            expected,
        )

    def test_user_operations_view(self):
        safe_address = Account.create().address

        response = self.client.get(
            reverse(
                "v1:account_abstraction:user-operations",
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
            reverse("v1:account_abstraction:user-operations", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = {
            "sender": safe_operation.user_operation.sender,
            "nonce": safe_operation.user_operation.nonce,
            "userOperationHash": safe_operation.user_operation.hash,
            "ethereumTxHash": safe_operation.user_operation.ethereum_tx_id,
            "initCode": "0x",
            "callData": "0x",
            "callDataGasLimit": safe_operation.user_operation.call_data_gas_limit,
            "verificationGasLimit": safe_operation.user_operation.verification_gas_limit,
            "preVerificationGas": safe_operation.user_operation.pre_verification_gas,
            "maxFeePerGas": safe_operation.user_operation.max_fee_per_gas,
            "maxPriorityFeePerGas": safe_operation.user_operation.max_priority_fee_per_gas,
            "paymaster": NULL_ADDRESS,
            "paymasterData": "0x",
            "signature": "0x",
            "entryPoint": safe_operation.user_operation.entry_point,
            "safeOperation": {
                "created": datetime_to_str(safe_operation.created),
                "modified": datetime_to_str(safe_operation.modified),
                "safeOperationHash": safe_operation.hash,
                "validAfter": datetime_to_str(safe_operation.valid_after),
                "validUntil": datetime_to_str(safe_operation.valid_until),
                "moduleAddress": safe_operation.module_address,
                "confirmations": [],
                "preparedSignature": None,
            },
        }
        self.assertDictEqual(
            response.json(),
            {"count": 1, "next": None, "previous": None, "results": [expected]},
        )
