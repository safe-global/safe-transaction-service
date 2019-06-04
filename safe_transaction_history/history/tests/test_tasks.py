import logging

from django.test import TestCase
from gnosis.eth import EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract

from gnosis.safe import SafeOperation, Safe
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe.signatures import signatures_to_bytes
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import MultisigConfirmation, MultisigTransaction
from ..tasks import check_approve_transaction
from .factories import (MultisigTransactionConfirmationFactory,
                        MultisigTransactionFactory)

logger = logging.getLogger(__name__)


class TestHistoryTasks(TestCase, SafeTestCaseMixin):
    WITHDRAW_AMOUNT = 50000000000000000

    @classmethod
    def setUpTestData(cls):
        cls.prepare_tests()

    def deploy_test_safe(self):
        owners = self.w3.eth.accounts[:4]
        initial_funding_wei = self.w3.toWei(0.01, 'ether')
        safe_create2_tx = super().deploy_test_safe(owners=owners, threshold=2, initial_funding_wei=initial_funding_wei)
        return (safe_create2_tx.safe_address, get_safe_contract(self.w3, safe_create2_tx.safe_address),
                safe_create2_tx.owners, NULL_ADDRESS, initial_funding_wei, safe_create2_tx.threshold)

    def test_task_flow_1(self):
        safe_address, safe_contract, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

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

        safe = Safe(safe_address, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(to, value, data, operation, safe_tx_gas, data_gas, gas_price, gas_token,
                                         refund_receiver, safe_nonce=nonce)
        safe_tx_hash = safe_tx.safe_tx_hash

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       owner=sender,
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner0.hex(), owners[0], retry=False)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                               block_number=self.w3.eth.blockNumber,
                                               owner=sender,
                                               transaction_hash=tx_hash_owner1.hex(),
                                               contract_transaction_hash=safe_tx_hash.hex())

        # v == 1, r = owner -> Signed previously
        signatures = signatures_to_bytes([(1, int(owner, 16), 0)
                                          for owner in
                                          sorted(owners[:2], key=lambda x: x.lower())])

        # Execute transaction
        safe_tx.signatures = signatures
        tx_exec_hash_owner1, _ = safe_tx.execute(self.ethereum_test_account.privateKey)

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), sender, retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.mined)

    def test_task_flow_2(self):
        safe_address, safe_contract, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

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

        safe = Safe(safe_address, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(to, value, data, operation, safe_tx_gas, data_gas, gas_price, gas_token,
                                         refund_receiver, safe_nonce=nonce)
        safe_tx_hash = safe_tx.safe_tx_hash

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        self.assertTrue(multisig_confirmation_check.mined)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        self.assertTrue(multisig_confirmation_check.mined)

        # send other approval from a third user
        sender = owners[2]
        tx_hash_owner2 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
        self.assertTrue(is_approved)

        multisig_confirmation = MultisigTransactionConfirmationFactory(multisig_transaction=multisig_transaction,
                                                                       block_number=self.w3.eth.blockNumber,
                                                                       owner=sender,
                                                                       transaction_hash=tx_hash_owner2.hex(),
                                                                       contract_transaction_hash=safe_tx_hash.hex())

        # Execute task
        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner2.hex(), sender, retry=False)

        # v == 1, r = owner -> Signed previously
        signatures = signatures_to_bytes([(1, int(owner, 16), 0)
                                          for owner in
                                          sorted(owners[:2], key=lambda x: x.lower())])

        # Execute transaction after owner 1 sent approval
        # from owners[1]
        safe_tx.signatures = signatures
        tx_exec_hash_owner2, _ = safe_tx.execute(self.ethereum_test_account.privateKey)

        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner2.hex(), owners[2], retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.mined)

    def test_block_number_different_confirmation_ok(self):
        safe_address, safe_contract, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

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

        safe = Safe(safe_address, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(to, value, data, operation, safe_tx_gas, data_gas, gas_price, gas_token,
                                         refund_receiver, safe_nonce=nonce)
        safe_tx_hash = safe_tx.safe_tx_hash

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        self.assertTrue(multisig_confirmation_check.mined)

    def test_confirmation_ko(self):
        safe_address, safe_contract, owners, funder, initial_funding_wei, _ = self.deploy_test_safe()

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

        safe = Safe(safe_address, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(to, value, data, operation, safe_tx_gas, data_gas, gas_price, gas_token,
                                         refund_receiver, safe_nonce=nonce)
        safe_tx_hash = safe_tx.safe_tx_hash

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        safe_address, safe_contract, owners, funder, initial_funding_wei, threshold = self.deploy_test_safe()

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

        safe = Safe(safe_address, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(to, value, data, operation, safe_tx_gas, data_gas, gas_price, gas_token,
                                         refund_receiver, safe_nonce=nonce)
        safe_tx_hash = safe_tx.safe_tx_hash

        # Send Tx signed by owner 0
        sender = owners[0]
        tx_hash_owner0 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        self.assertTrue(multisig_confirmation_check.mined)

        # Send Tx signed by owner 1
        sender = owners[1]
        tx_hash_owner1 = safe_contract.functions.approveHash(safe_tx_hash).transact({'from': sender})
        is_approved = safe_contract.functions.approvedHashes(sender, safe_tx_hash).call()
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
        self.assertTrue(multisig_confirmation_check.mined)

        # v == 1, r = owner -> Signed previously
        signatures = signatures_to_bytes([(1, int(owner, 16), 0)
                                          for owner in
                                          sorted(owners[:2], key=lambda x: x.lower())])



        # Execute transaction
        safe_tx.signatures = signatures
        tx_exec_hash_owner1, _ = safe_tx.execute(self.ethereum_test_account.privateKey)

        check_approve_transaction(safe_address, safe_tx_hash.hex(), tx_hash_owner1.hex(), sender, retry=False)

        multisig_transaction_check = MultisigTransaction.objects.get(safe=safe_address, to=to,
                                                                     value=value, nonce=nonce)
        self.assertTrue(multisig_transaction_check.mined)
