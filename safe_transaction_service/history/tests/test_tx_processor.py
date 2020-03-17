import logging

from eth_account import Account
from web3 import Web3

from ..indexers.tx_processor import SafeTxProcessor
from ..models import (InternalTxDecoded, ModuleTransaction,
                      MultisigTransaction, SafeContract, SafeStatus)
from .factories import EthereumTxFactory, InternalTxDecodedFactory
from .test_internal_tx_indexer import TestInternalTxIndexer

logger = logging.getLogger(__name__)


class TestSafeTxProcessor(TestInternalTxIndexer):
    def test_tx_processor_using_internal_tx_indexer(self):
        self.test_internal_tx_indexer()
        tx_processor = SafeTxProcessor()
        self.assertEqual(InternalTxDecoded.objects.count(), 2)  # Setup and execute tx
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(len(internal_txs_decoded), 1)  # Safe not indexed yet
        number_processed = tx_processor.process_decoded_transactions(internal_txs_decoded)  # Index using `setup` trace
        self.assertEqual(len(number_processed), 1)  # Setup trace
        self.assertEqual(SafeContract.objects.count(), 1)

        safe_status = SafeStatus.objects.first()
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.nonce, 0)
        self.assertEqual(safe_status.threshold, 1)

        # Decode again now that Safe is indexed (with `setup` call)
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(len(internal_txs_decoded), 1)  # Safe indexed, execute tx can be decoded now
        number_processed = tx_processor.process_decoded_transactions(internal_txs_decoded)
        self.assertEqual(len(number_processed), 1)  # Setup trace
        safe_status = SafeStatus.objects.get(nonce=1)
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.threshold, 1)

    def test_tx_processor_using_internal_tx_indexer_with_existing_safe(self):
        self.test_internal_tx_indexer()
        tx_processor = SafeTxProcessor()
        tx_processor.process_decoded_transactions(InternalTxDecoded.objects.pending_for_safes())
        safe_contract: SafeContract = SafeContract.objects.first()
        self.assertGreater(safe_contract.erc20_block_number, 0)
        safe_contract.erc20_block_number = 0
        safe_contract.save(update_fields=['erc20_block_number'])

        SafeStatus.objects.all().delete()
        InternalTxDecoded.objects.update(processed=False)
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(internal_txs_decoded.count(), 2)
        self.assertEqual(internal_txs_decoded[0].function_name, 'setup')
        tx_processor.process_decoded_transactions(internal_txs_decoded)
        safe_contract.refresh_from_db()
        self.assertGreater(safe_contract.erc20_block_number, 0)

    def test_tx_processor_with_factory(self):
        tx_processor = SafeTxProcessor()
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        tx_processor.process_decoded_transaction(
            InternalTxDecodedFactory(function_name='setup', owner=owner, threshold=threshold,
                                     fallback_handler=fallback_handler,
                                     internal_tx__to=master_copy,
                                     internal_tx___from=safe_address)
        )
        self.assertTrue(SafeContract.objects.get(address=safe_address))
        safe_status = SafeStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.owners, [owner])
        self.assertEqual(safe_status.threshold, threshold)

        # execTransaction should be calling addOwnerWithThreshold, so we process it together
        threshold = 2
        new_owner = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='addOwnerWithThreshold', owner=new_owner, threshold=threshold,
                                         internal_tx___from=safe_address)
            ])

        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertCountEqual(safe_status.owners, [owner, new_owner])
        self.assertEqual(safe_status.nonce, 1)
        self.assertEqual(safe_status.threshold, threshold)

        another_owner = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='swapOwner', old_owner=owner, owner=another_owner,
                                         internal_tx___from=safe_address)
            ])
        self.assertEqual(SafeStatus.objects.count(), 5)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertCountEqual(safe_status.owners, [another_owner, new_owner])
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, threshold)

        threshold = 1
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='removeOwner', old_owner=another_owner, threshold=threshold,
                                         internal_tx___from=safe_address)
            ])
        self.assertEqual(SafeStatus.objects.count(), 7)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.owners, [new_owner])
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, threshold)

        fallback_handler = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='setFallbackHandler', fallback_handler=fallback_handler,
                                         internal_tx___from=safe_address)
            ])
        self.assertEqual(SafeStatus.objects.count(), 9)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.nonce, 4)

        master_copy = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='changeMasterCopy', master_copy=master_copy,
                                         internal_tx___from=safe_address)
            ])
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.nonce, 5)
        self.assertEqual(safe_status.enabled_modules, [])

        module = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='enableModule', module=module,
                                         internal_tx___from=safe_address)
            ])
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.enabled_modules, [module])
        self.assertEqual(safe_status.nonce, 6)

        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransaction',
                                         internal_tx___from=safe_address),
                InternalTxDecodedFactory(function_name='disableModule', module=module,
                                         internal_tx___from=safe_address)
            ])
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.nonce, 7)

        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(function_name='execTransactionFromModule',
                                         internal_tx___from=safe_address),
            ])
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        self.assertEqual(safe_status.nonce, 7)  # Nonce not incrementing
        self.assertEqual(ModuleTransaction.objects.count(), 1)

        self.assertEqual(MultisigTransaction.objects.count(),
                         InternalTxDecoded.objects.filter(function_name='execTransaction').count())

    def test_tx_processor_failed(self):
        tx_processor = SafeTxProcessor()
        # Event for Safes < 1.1.1
        logs = [{'data': '0x0034bff0dedc4c75f43df64a179ff26d56b99fa742fcfaeeee51e2da4e279b67',
                 'topics': ['0xabfd711ecdd15ae3a6b3ad16ff2e9d81aec026a39d16725ee164be4fbf857a7c']}]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertTrue(tx_processor.is_failed(ethereum_tx, logs[0]['data']))
        self.assertFalse(tx_processor.is_failed(ethereum_tx, Web3.keccak(text='hola').hex()))

        # Event for Safes >= 1.1.1
        safe_tx_hash = '0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311'
        logs = [{'data': '0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311'
                         '0000000000000000000000000000000000000000000000000000000000000000',
                 'topics': ['0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23']}]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertTrue(tx_processor.is_failed(ethereum_tx, safe_tx_hash))
        self.assertFalse(tx_processor.is_failed(ethereum_tx, Web3.keccak(text='hola').hex()))
