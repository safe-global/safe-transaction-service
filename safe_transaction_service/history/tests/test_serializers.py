from django.test import TestCase

from eth_account import Account
from rest_framework.exceptions import ValidationError
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from ...history.serializers import SafeMultisigTransactionResponseSerializer
from ...history.tests.factories import (
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
)


class TestSerializers(SafeTestCaseMixin, TestCase):

    def test_safe_multisig_transaction_response_serializer(self):
        safe_owner = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner.address])
        safe_address = safe.address

        multisig_transaction_invalid_tx_hash = MultisigTransactionFactory(
            safe=safe_address, nonce=0, ethereum_tx=None, trusted=True
        )
        # Invalid Tx hash
        MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction_invalid_tx_hash,
            force_sign_with_account=safe_owner,
        )

        serializer = SafeMultisigTransactionResponseSerializer(
            instance=multisig_transaction_invalid_tx_hash
        )
        with self.assertRaises(ValidationError):
            serializer.get_confirmations(multisig_transaction_invalid_tx_hash)

        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        # Signer not owner
        safe_not_owner = Account.create()
        MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            force_sign_with_account=safe_not_owner,
        )

        serializer = SafeMultisigTransactionResponseSerializer(
            instance=multisig_transaction
        )
        with self.assertRaises(ValidationError):
            serializer.get_confirmations(multisig_transaction)

        # Signature of a different safe-tx-hash
        multisig_transaction_invalid = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        multisig_confirmation_invalid_tx = MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction_invalid,
            force_sign_with_account=safe_owner,
        )
        multisig_confirmation_invalid_tx.safe_tx_hash = (
            multisig_transaction.safe_tx_hash
        )
        multisig_confirmation_invalid_tx.save()

        with self.assertRaises(ValidationError):
            serializer.get_confirmations(multisig_transaction)

        # Signature of a different owner
        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        multisig_confirmation_invalid_owner = MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            force_sign_with_account=safe_owner,
        )
        multisig_confirmation_invalid_owner.owner = Account.create().address
        multisig_confirmation_invalid_owner.save()

        with self.assertRaises(ValidationError):
            serializer.get_confirmations(multisig_transaction)

        # valid signature
        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            force_sign_with_account=safe_owner,
        )

        serializer = SafeMultisigTransactionResponseSerializer(
            instance=multisig_transaction
        )
        confirmations = serializer.get_confirmations(multisig_transaction)

        self.assertIsNotNone(confirmations)
        self.assertEqual(len(confirmations), 1)
        self.assertEqual(confirmations[0]["owner"], safe_owner.address)

        # Test signatures without tx hash (Not executed)
        multisig_transaction_with_signatures_and_not_executed = (
            MultisigTransactionFactory(
                safe=safe_address,
                nonce=0,
                signatures=b"0x12344",
                ethereum_tx=None,
                trusted=True,
                enable_safe_tx_hash_calculation=True,
            )
        )
        serializer = SafeMultisigTransactionResponseSerializer(
            instance=multisig_transaction_with_signatures_and_not_executed
        )
        with self.assertRaises(ValidationError):
            serializer.get_signatures(
                multisig_transaction_with_signatures_and_not_executed
            )

        # Test get signatures
        signatures = serializer.get_signatures(multisig_transaction)
        self.assertIsNotNone(signatures)
