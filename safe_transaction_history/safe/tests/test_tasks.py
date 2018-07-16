import logging
from random import randint

from django.test import TestCase

from .safe_test_case import TestCaseWithSafeContractMixin
from ..ethereum_service import EthereumServiceProvider
from ..models import MultisigTransaction, MultisigConfirmation
from ..tasks import check_approve_transaction
from .factories import MultisigTransactionFactory, MultisigTransactionConfirmationFactory

logger = logging.getLogger(__name__)


class TestTasks(TestCase, TestCaseWithSafeContractMixin):
    WITHDRAW_AMOUNT = 50000000000000000

    @classmethod
    def setUpTestData(cls):
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3
        cls.prepare_safe_tests()

    def test_task_execution(self):
        safe_address, safe_instance, owners, funder, fund_amount = self.deploy_safe()
        safe_nonce = randint(0, 10)

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=owners[0], value=self.WITHDRAW_AMOUNT,
                                                          operation=self.CALL_OPERATION, nonce=safe_nonce)

        # Send Tx signed by owner 0
        tx_hash_owner0 = safe_instance.functions.approveTransactionWithParameters(
            owners[0], self.WITHDRAW_AMOUNT, b'', self.CALL_OPERATION, safe_nonce
        ).transact({
            'from': owners[0]
        })

        internal_tx_hash_owner0 = safe_instance.functions.getTransactionHash(
            owners[0], self.WITHDRAW_AMOUNT, b'', self.CALL_OPERATION, safe_nonce
        ).call({
            'from': owners[0]
        })

        is_approved = safe_instance.functions.isApproved(internal_tx_hash_owner0.hex(), owners[0]).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=owners[0],
                                                                       contract_transaction_hash=internal_tx_hash_owner0.hex())

        # Execute task
        check_approve_transaction(safe_address, internal_tx_hash_owner0.hex(), owners[0], retry=False)

        # Send Tx signed by owner 1
        tx_hash_owner1 = safe_instance.functions.approveTransactionWithParameters(
            owners[0], self.WITHDRAW_AMOUNT, b'', self.CALL_OPERATION, safe_nonce
        ).transact({
            'from': owners[1]
        })

        internal_tx_hash_owner1 = safe_instance.functions.getTransactionHash(
            owners[0], self.WITHDRAW_AMOUNT, b'', self.CALL_OPERATION, safe_nonce
        ).call({
            'from': owners[1]
        })

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=owners[1],
                                                                       contract_transaction_hash=internal_tx_hash_owner1.hex())


        tx_hash_owner1 = safe_instance.functions.execTransactionIfApproved(
            owners[0], self.WITHDRAW_AMOUNT, b'', self.CALL_OPERATION, safe_nonce
        ).transact({
            'from': owners[1]
        })

        # Execute task
        check_approve_transaction(safe_address, internal_tx_hash_owner1.hex(), owners[1], retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=owners[0],
                                                                     value=self.WITHDRAW_AMOUNT, nonce=safe_nonce)
        self.assertTrue(multisig_transaction_check.status)