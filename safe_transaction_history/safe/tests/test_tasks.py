import logging
from random import randint

from django.test import TestCase
from django_eth.constants import NULL_ADDRESS

from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import SafeOperation
from gnosis.safe.tests.factories import get_eth_address_with_key
from gnosis.safe.tests.safe_test_case import TestCaseWithSafeContractMixin

from ..models import MultisigConfirmation, MultisigTransaction
from ..tasks import check_approve_transaction
from .factories import (MultisigTransactionConfirmationFactory,
                        MultisigTransactionFactory)

logger = logging.getLogger(__name__)


class TestHistoryTasks(TestCase, TestCaseWithSafeContractMixin):
    WITHDRAW_AMOUNT = 50000000000000000

    @classmethod
    def setUpTestData(cls):
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3
        cls.prepare_safe_tests()

    def test_task_flow(self):
        safe_address, safe_instance, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

        to, _ = get_eth_address_with_key()
        value = self.WITHDRAW_AMOUNT
        data = b''
        operation = SafeOperation.CALL.value
        safe_tx_gas = 500000
        data_gas = 500000
        gas_price = 1
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = 0

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=to, value=value,
                                                          operation=operation, nonce=nonce)

        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data, operation, safe_tx_gas,
                                                              data_gas, gas_price, gas_token, refund_receiver, nonce)

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner0.hex(), owners[0], retry=False)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       block_number=self.w3.eth.blockNumber,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner1.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # v == 1, r = owner -> Signed previously
        signatures = self.safe_service.signatures_to_bytes([(1, int(owner, 16), 0)
                                                            for owner in
                                                            sorted(owners[:2], key=lambda x: x.lower())])

        # Execute transaction
        tx_exec_hash_owner1, _ = self.safe_service.send_multisig_tx(safe_address, to, value, data, operation,
                                                                    safe_tx_gas, data_gas, gas_price, gas_token,
                                                                    refund_receiver, signatures)

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), sender, retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.status)

    def test_task_flow_bis(self):
        safe_address, safe_instance, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

        to, _ = get_eth_address_with_key()
        value = self.WITHDRAW_AMOUNT
        data = b''
        operation = SafeOperation.CALL.value
        safe_tx_gas = 500000
        data_gas = 500000
        gas_price = 1
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = 0

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=to, value=value,
                                                          operation=operation, nonce=nonce)

        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data, operation, safe_tx_gas,
                                                              data_gas, gas_price, gas_token, refund_receiver, nonce)

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner0.hex(), sender,
                                  retry=False)

        multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex())
        self.assertTrue(multisig_confirmation_check.status)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       block_number=self.w3.eth.blockNumber,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner1.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), owners[1], retry=False)

        multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner1.hex())
        self.assertTrue(multisig_confirmation_check.status)

        # send other approval from a third user
        sender = owners[2]
        tx_hash_owner2 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       block_number=self.w3.eth.blockNumber,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner2.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner2.hex(), sender, retry=False)

        # v == 1, r = owner -> Signed previously
        signatures = self.safe_service.signatures_to_bytes([(1, int(owner, 16), 0)
                                                            for owner in
                                                            sorted(owners[:2], key=lambda x: x.lower())])

        # Execute transaction after owner 1 sent approval
        # from owners[1]
        tx_exec_hash_owner2, _ = self.safe_service.send_multisig_tx(safe_address, to, value, data, operation,
                                                                    safe_tx_gas, data_gas, gas_price, gas_token,
                                                                    refund_receiver, signatures)

        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner2.hex(), owners[2], retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.status)

    def test_block_number_different_confirmation_ok(self):
        safe_address, safe_instance, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

        to, _ = get_eth_address_with_key()
        value = self.WITHDRAW_AMOUNT
        data = b''
        operation = SafeOperation.CALL.value
        safe_tx_gas = 500000
        data_gas = 500000
        gas_price = 1
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = 0

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=to, value=value,
                                                          operation=operation, nonce=nonce)

        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data, operation, safe_tx_gas,
                                                              data_gas, gas_price, gas_token, refund_receiver, nonce)

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        multisig_confirmation.block_number = multisig_confirmation.block_number + self.w3.eth.blockNumber
        multisig_confirmation.save()

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner0.hex(), sender, retry=False)

        multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex())
        self.assertTrue(multisig_confirmation_check.status)

    def test_confirmation_ko(self):
        safe_address, safe_instance, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

        to, _ = get_eth_address_with_key()
        value = self.WITHDRAW_AMOUNT
        data = b''
        operation = SafeOperation.CALL.value
        safe_tx_gas = 500000
        data_gas = 500000
        gas_price = 1
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = 0

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=to, value=value,
                                                          operation=operation, nonce=nonce)

        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data, operation, safe_tx_gas,
                                                              data_gas, gas_price, gas_token, refund_receiver, nonce)

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        # Simulate reorg, transaction not existing on the blockchain
        fake_transaction_hash = self.w3.sha3(text='hello').hex()

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       transaction_hash=fake_transaction_hash,
                                                                       contract_transaction_hash=safe_tx_hash.hex(),
                                                                       block_number=self.w3.eth.blockNumber - 1)

        # Execute task
        with self.settings(SAFE_REORG_BLOCKS=0):
            check_approve_transaction(safe_address, safe_tx_hash.hex(), fake_transaction_hash, sender, retry=False)

        with self.assertRaises(MultisigConfirmation.DoesNotExist):
            multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                           owner=sender,
                                                                           transaction_hash=fake_transaction_hash)

    def test_block_number_different(self):
        safe_address, safe_instance, owners, funder, initial_funding_wei, threshold = self.deploy_test_safe()

        to, _ = get_eth_address_with_key()
        value = self.WITHDRAW_AMOUNT
        data = b''
        operation = SafeOperation.CALL.value
        safe_tx_gas = 500000
        data_gas = 500000
        gas_price = 1
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = 0

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, to=to, value=value,
                                                          operation=operation, nonce=nonce)

        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data, operation, safe_tx_gas,
                                                              data_gas, gas_price, gas_token, refund_receiver, nonce)

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        multisig_confirmation.block_number = self.w3.eth.blockNumber - 1
        multisig_confirmation.save()

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner0.hex(), sender, retry=False)

        multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner0.hex())
        self.assertTrue(multisig_confirmation_check.status)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_instance.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_instance.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       block_number=self.w3.eth.blockNumber,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner1.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        multisig_confirmation.block_number = self.w3.eth.blockNumber - 1
        multisig_confirmation.save()

        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), sender, retry=False)

        multisig_confirmation_check = MultisigConfirmation.objects.get(multisig_transaction__safe=safe_address,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner1.hex())
        self.assertTrue(multisig_confirmation_check.status)

        # v == 1, r = owner -> Signed previously
        signatures = self.safe_service.signatures_to_bytes([(1, int(owner, 16), 0)
                                                            for owner in
                                                            sorted(owners[:2], key=lambda x: x.lower())])



        # Execute transaction
        tx_exec_hash_owner1, _ = self.safe_service.send_multisig_tx(safe_address, to, value, data, operation,
                                                                    safe_tx_gas, data_gas, gas_price, gas_token,
                                                                    refund_receiver, signatures)

        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), sender, retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.status)
