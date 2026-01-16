import datetime
from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient
from safe_eth.eth.tests.mocks.mock_bundler import (
    safe_4337_address,
    safe_4337_chain_id_mock,
    safe_4337_module_address_mock,
    user_operation_v07_chain_id,
)
from safe_eth.eth.tests.mocks.mock_bundler import (
    user_operation_v07_mock_1 as user_operation_v07_mock,
)
from safe_eth.safe.safe_signature import SafeSignature, SafeSignatureType
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.history.tests.factories import EthereumTxFactory

from .. import models
from ..serializers import SafeOperationSerializer
from . import factories


@mock.patch("safe_eth.eth.get_auto_ethereum_client")
class TestSafeOperationSerializer(TestCase):
    """Tests for SafeOperationSerializer"""

    def test_serializer_invalid_module_address(
        self, get_auto_ethereum_client_mock: MagicMock
    ):
        """Test that invalid module address is rejected"""
        account = Account.create()
        safe_address = Account.create().address
        invalid_module = Account.create().address

        data = {
            "nonce": 0,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": invalid_module,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("module_address", serializer.errors)

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    def test_serializer_module_entrypoint_mismatch(
        self,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that module address must match entry point version"""
        account = Account.create()
        safe_address = Account.create().address

        # Use v6 entry point with v7 module address
        data = {
            "nonce": 0,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": settings.ETHEREUM_4337_SAFE_MODULE_ADDRESS_V07,  # Wrong version
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("Invalid Module address", str(serializer.errors))

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_rejects_factory_field(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that factory field (v7) is rejected for v6 entry point"""
        account = Account.create()
        safe_address = safe_4337_address

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
            "factory": Account.create().address,  # v7 field - should be rejected
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("factory", str(serializer.errors).lower())

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_rejects_paymaster_field(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that paymaster field (v7) is rejected for v6 entry point"""
        account = Account.create()
        safe_address = safe_4337_address

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
            "paymaster": Account.create().address,  # v7 field - should be rejected
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("Paymaster", str(serializer.errors))

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=user_operation_v07_chain_id,
    )
    def test_serializer_v7_rejects_init_code_field(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that init_code field (v6) is rejected for v7 entry point"""
        account = Account.create()
        safe_address = user_operation_v07_mock["result"]["userOperation"]["sender"]

        v7_entry_point = settings.ETHEREUM_4337_ENTRYPOINT_V7
        v7_module_address = settings.ETHEREUM_4337_SAFE_MODULE_ADDRESS_V07

        data = {
            "nonce": 0,
            "init_code": "0x1234",  # v6 field - should be rejected for v7
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": v7_entry_point,
            "valid_after": None,
            "valid_until": None,
            "module_address": v7_module_address,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        # init_code validation fails at field level (contract deployed) or validate level (v7)
        errors_str = str(serializer.errors).lower()
        self.assertTrue(
            "init_code" in errors_str,
            f"Expected init_code error, got: {serializer.errors}",
        )

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=user_operation_v07_chain_id,
    )
    def test_serializer_v7_rejects_paymaster_and_data_field(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that paymaster_and_data field (v6) is rejected for v7 entry point"""
        account = Account.create()
        safe_address = user_operation_v07_mock["result"]["userOperation"]["sender"]

        v7_entry_point = settings.ETHEREUM_4337_ENTRYPOINT_V7
        v7_module_address = settings.ETHEREUM_4337_SAFE_MODULE_ADDRESS_V07

        data = {
            "nonce": 0,
            "paymaster_and_data": "0x" + "00" * 20,  # v6 field - should be rejected
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": v7_entry_point,
            "valid_after": None,
            "valid_until": None,
            "module_address": v7_module_address,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("paymaster_and_data", str(serializer.errors).lower())

    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_nonce_too_low(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that nonce too low is rejected"""
        account = Account.create()
        safe_address = safe_4337_address
        get_owners_mock.return_value = [account.address]

        # Create existing operation with higher nonce that has been executed
        ethereum_tx = EthereumTxFactory()
        factories.UserOperationFactory(
            nonce=5,
            sender=safe_address,
            ethereum_tx=ethereum_tx,
        )

        data = {
            "nonce": 3,  # Lower than existing executed nonce
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("nonce", serializer.errors)
        self.assertIn("too low", str(serializer.errors))

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_valid_data(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test SafeOperationSerializer with valid v6 data"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = b"\x00" * 65
        parse_signature_mock.return_value = [mock_safe_signature]

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_save_v6(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test saving a v6 SafeOperation creates correct models"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature with all required attributes
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Save the operation
        user_operation_model = serializer.save()

        # Verify models were created
        self.assertEqual(models.UserOperation.objects.count(), 1)
        self.assertEqual(models.SafeOperation.objects.count(), 1)

        # Verify v6 specific fields
        self.assertIsNone(user_operation_model.factory)
        self.assertIsNone(user_operation_model.factory_data)
        self.assertIsNone(user_operation_model.paymaster_verification_gas_limit)
        self.assertIsNone(user_operation_model.paymaster_post_op_gas_limit)

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_duplicate_safe_operation(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that duplicate SafeOperation is rejected"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature with all required attributes
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        # First save should succeed
        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        # Second save with same data should fail
        serializer2 = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer2.is_valid())
        self.assertIn("non_field_errors", serializer2.errors)
        self.assertIn("already exists", str(serializer2.errors))

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_invalid_signer(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that signature from non-owner is rejected"""
        account = Account.create()
        non_owner = Account.create()
        safe_address = safe_4337_address

        # Only account is owner, but signature is from non_owner
        get_owners_mock.return_value = [account.address]

        # Create mock signature from non-owner
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = non_owner.address  # Not an owner!
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = b"\x00" * 65
        parse_signature_mock.return_value = [mock_safe_signature]

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                non_owner.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("is not an owner", str(serializer.errors))

    # ==================== Paymaster Tests ====================

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_paymaster_and_data_too_short(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that paymaster_and_data shorter than 20 bytes is rejected"""
        account = Account.create()
        safe_address = safe_4337_address

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": "0x" + "00" * 19,  # Only 19 bytes - too short
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("paymaster_and_data", serializer.errors)
        self.assertIn("at least 20 bytes", str(serializer.errors))

    @mock.patch.object(EthereumClient, "is_contract")
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_paymaster_not_contract(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that paymaster address must be a deployed contract"""
        account = Account.create()
        safe_address = safe_4337_address
        paymaster_address = Account.create().address

        # Safe is deployed, but paymaster is not
        def is_contract_side_effect(address):
            if address.lower() == safe_address.lower():
                return True
            return False  # Paymaster is not a contract

        is_contract_mock.side_effect = is_contract_side_effect

        # paymaster_and_data = paymaster address (20 bytes) + optional data
        paymaster_and_data = paymaster_address.lower().replace("0x", "") + "deadbeef"

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": "0x" + paymaster_and_data,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("paymaster_and_data", serializer.errors)
        self.assertIn("not found in blockchain", str(serializer.errors))

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_valid_paymaster_and_data(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid paymaster_and_data is accepted and saved"""
        account = Account.create()
        safe_address = safe_4337_address
        paymaster_address = Account.create().address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        # paymaster_and_data = paymaster address (20 bytes) + data
        paymaster_data = "deadbeef1234"
        paymaster_and_data = (
            paymaster_address.lower().replace("0x", "") + paymaster_data
        )

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": "0x" + paymaster_and_data,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Save and verify paymaster fields
        user_operation = serializer.save()
        self.assertEqual(user_operation.paymaster.lower(), paymaster_address.lower())
        self.assertEqual(user_operation.paymaster_data, HexBytes("0x" + paymaster_data))

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=user_operation_v07_chain_id,
    )
    def test_serializer_v7_paymaster_fields_saved(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that v7 paymaster fields are saved correctly"""
        account = Account.create()
        safe_address = Account.create().address
        paymaster_address = Account.create().address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        v7_entry_point = settings.ETHEREUM_4337_ENTRYPOINT_V7
        v7_module_address = settings.ETHEREUM_4337_SAFE_MODULE_ADDRESS_V07

        data = {
            "nonce": 0,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "factory": None,
            "factory_data": None,
            "paymaster": paymaster_address,
            "paymaster_data": "0xdeadbeef1234",
            "paymaster_verification_gas_limit": 75000,
            "paymaster_post_op_gas_limit": 25000,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": v7_entry_point,
            "valid_after": None,
            "valid_until": None,
            "module_address": v7_module_address,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Save and verify paymaster fields
        user_operation = serializer.save()
        self.assertEqual(user_operation.paymaster.lower(), paymaster_address.lower())
        self.assertEqual(user_operation.paymaster_data, HexBytes("0xdeadbeef1234"))
        self.assertEqual(user_operation.paymaster_verification_gas_limit, 75000)
        self.assertEqual(user_operation.paymaster_post_op_gas_limit, 25000)

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=user_operation_v07_chain_id,
    )
    def test_serializer_v7_paymaster_data_without_paymaster(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that paymaster_data without paymaster is rejected for v7"""
        account = Account.create()
        safe_address = Account.create().address

        v7_entry_point = settings.ETHEREUM_4337_ENTRYPOINT_V7
        v7_module_address = settings.ETHEREUM_4337_SAFE_MODULE_ADDRESS_V07

        data = {
            "nonce": 0,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "factory": None,
            "factory_data": None,
            "paymaster": None,  # No paymaster
            "paymaster_data": "0xdeadbeef",  # But paymaster_data is provided
            "paymaster_verification_gas_limit": None,
            "paymaster_post_op_gas_limit": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": v7_entry_point,
            "valid_after": None,
            "valid_until": None,
            "module_address": v7_module_address,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("paymaster_data", str(serializer.errors).lower())

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_v6_paymaster_verification_gas_limit_rejected(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that v7 paymaster gas fields are rejected for v6"""
        account = Account.create()
        safe_address = safe_4337_address

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "paymaster_verification_gas_limit": 50000,  # v7 field
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("paymaster", str(serializer.errors).lower())

    # ==================== Valid After / Valid Until Tests ====================

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_valid_until_in_past_rejected(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid_until in the past is rejected"""
        account = Account.create()
        safe_address = safe_4337_address

        # Set valid_until to 1 hour in the past
        past_time = timezone.now() - datetime.timedelta(hours=1)

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": past_time.isoformat(),
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("valid_until", serializer.errors)
        self.assertIn(
            "cannot be previous to the current timestamp", str(serializer.errors)
        )

    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_valid_after_greater_than_valid_until_rejected(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid_after greater than valid_until is rejected"""
        account = Account.create()
        safe_address = safe_4337_address

        # Set valid_after to be after valid_until
        valid_until = timezone.now() + datetime.timedelta(hours=1)
        valid_after = timezone.now() + datetime.timedelta(hours=2)

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(
                account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))["signature"]
            ),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": valid_after.isoformat(),
            "valid_until": valid_until.isoformat(),
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)
        self.assertIn("valid_after", str(serializer.errors).lower())
        self.assertIn("cannot be higher than", str(serializer.errors).lower())

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_valid_after_and_valid_until_saved(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid_after and valid_until are saved correctly"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        # Set valid times in the future
        valid_after = timezone.now() + datetime.timedelta(hours=1)
        valid_until = timezone.now() + datetime.timedelta(hours=2)

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": valid_after.isoformat(),
            "valid_until": valid_until.isoformat(),
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Save and verify the values
        user_operation = serializer.save()
        safe_operation = user_operation.safe_operation

        # Compare timestamps (allowing for minor differences due to serialization)
        self.assertIsNotNone(safe_operation.valid_after)
        self.assertIsNotNone(safe_operation.valid_until)
        self.assertAlmostEqual(
            safe_operation.valid_after.timestamp(),
            valid_after.timestamp(),
            delta=1,  # Allow 1 second difference
        )
        self.assertAlmostEqual(
            safe_operation.valid_until.timestamp(),
            valid_until.timestamp(),
            delta=1,
        )

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_valid_after_only(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid_after alone is accepted"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        valid_after = timezone.now() + datetime.timedelta(hours=1)

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": valid_after.isoformat(),
            "valid_until": None,
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        user_operation = serializer.save()
        safe_operation = user_operation.safe_operation

        self.assertIsNotNone(safe_operation.valid_after)
        self.assertIsNone(safe_operation.valid_until)

    @mock.patch.object(SafeSignature, "parse_signature")
    @mock.patch.object(
        SafeOperationSerializer,
        "_get_owners",
        autospec=True,
    )
    @mock.patch.object(EthereumClient, "is_contract", return_value=True)
    @mock.patch.object(
        EthereumClient,
        "get_chain_id",
        autospec=True,
        return_value=safe_4337_chain_id_mock,
    )
    def test_serializer_valid_until_only(
        self,
        get_chain_id_mock: MagicMock,
        is_contract_mock: MagicMock,
        get_owners_mock: MagicMock,
        parse_signature_mock: MagicMock,
        get_auto_ethereum_client_mock: MagicMock,
    ):
        """Test that valid_until alone is accepted"""
        account = Account.create()
        safe_address = safe_4337_address

        get_owners_mock.return_value = [account.address]

        # Create mock signature
        signature_bytes = account.unsafe_sign_hash(HexBytes("0x" + "00" * 32))[
            "signature"
        ]
        mock_safe_signature = MagicMock()
        mock_safe_signature.owner = account.address
        mock_safe_signature.is_valid.return_value = True
        mock_safe_signature.signature = signature_bytes
        mock_safe_signature.export_signature.return_value = signature_bytes
        mock_safe_signature.signature_type = SafeSignatureType.EOA
        parse_signature_mock.return_value = [mock_safe_signature]

        valid_until = timezone.now() + datetime.timedelta(hours=1)

        data = {
            "nonce": 0,
            "init_code": None,
            "call_data": "0x1234",
            "call_gas_limit": 100000,
            "verification_gas_limit": 100000,
            "pre_verification_gas": 50000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 1000000000,
            "paymaster_and_data": None,
            "signature": to_0x_hex_str(signature_bytes),
            "entry_point": settings.ETHEREUM_4337_ENTRYPOINT_V6,
            "valid_after": None,
            "valid_until": valid_until.isoformat(),
            "module_address": safe_4337_module_address_mock,
        }

        serializer = SafeOperationSerializer(
            data=data, context={"safe_address": safe_address}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        user_operation = serializer.save()
        safe_operation = user_operation.safe_operation

        self.assertIsNone(safe_operation.valid_after)
        self.assertIsNotNone(safe_operation.valid_until)
