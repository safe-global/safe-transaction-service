import logging
from random import randint

from django.conf import settings
from django.test import TestCase

from .safe_test_case import TestCaseWithSafeContractMixin
from ..ethereum_service import EthereumServiceProvider
from ..models import MultisigTransaction, MultisigConfirmation
from ..tasks import check_approve_transaction

logger = logging.getLogger(__name__)


class TestTasks(TestCase, TestCaseWithSafeContractMixin):
    WITHDRAW_AMOUNT = 50000000000000000

    @classmethod
    def setUpTestData(cls):
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3
        cls.prepare_safe_tests()

    def test_task(self):
        safe_address, safe_instance, owners, funder, fund_amount = self.deploy_safe()
        safe_nonce = randint(0, 10)

        # Send Tx signed by owner 1
        tx_hash_owner1 = safe_instance.functions.approveTransactionWithParameters(
            owners[0], self.WITHDRAW_AMOUNT, b'', 0, safe_nonce
        ).transact({
            'from': owners[1]
        })

        internal_tx_hash_owner1 = safe_instance.functions.getTransactionHash(
            owners[0], self.WITHDRAW_AMOUNT, b'', 0, safe_nonce
        ).call({
            'from': owners[1]
        })
        check_approve_transaction.delay(safe_address, internal_tx_hash_owner1.hex(), retry=False)
        # TODO checks

