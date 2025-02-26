from django.test import TestCase

from eth_account import Account
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.utils.exceptions import InternalValidationError

from ..serializers import SafeMessageResponseSerializer
from .factories import SafeMessageConfirmationFactory, SafeMessageFactory


class TestSerializers(SafeTestCaseMixin, TestCase):

    def test_safe_message_response_serializer(self):
        safe_address = self.deploy_test_safe().address
        safe_message = SafeMessageFactory(safe=safe_address)
        SafeMessageConfirmationFactory(safe_message=safe_message)

        safe_message.message = "modified message"
        safe_message.save(update_fields=["message"])

        serializer = SafeMessageResponseSerializer(instance=safe_message)
        # Test different Hash
        with self.assertRaises(InternalValidationError):
            serializer.get_confirmations(safe_message)

        safe_message = SafeMessageFactory(safe=safe_address)
        SafeMessageConfirmationFactory(safe_message=safe_message, signature=b"0x1234")

        serializer = SafeMessageResponseSerializer(instance=safe_message)

        # Test invalid signature
        with self.assertRaises(InternalValidationError):
            serializer.get_confirmations(safe_message)

        safe_message = SafeMessageFactory(safe=safe_address)
        SafeMessageConfirmationFactory(
            safe_message=safe_message, owner=Account.create().address
        )

        serializer = SafeMessageResponseSerializer(instance=safe_message)

        # Test invalid owner
        with self.assertRaises(InternalValidationError):
            serializer.get_confirmations(safe_message)

        safe_message = SafeMessageFactory(safe=safe_address)
        SafeMessageConfirmationFactory(safe_message=safe_message)

        serializer = SafeMessageResponseSerializer(instance=safe_message)

        # Test get_confirmations
        self.assertIsNotNone(serializer.get_confirmations(safe_message))
