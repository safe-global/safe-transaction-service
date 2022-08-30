from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes
from web3.datastructures import AttributeDict
from web3.types import LogReceipt

from gnosis.eth.constants import NULL_ADDRESS, SENTINEL_ADDRESS
from gnosis.eth.contracts import get_safe_V1_3_0_contract
from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..indexers import SafeEventsIndexer, SafeEventsIndexerProvider
from ..indexers.tx_processor import SafeTxProcessor
from ..models import (
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    MultisigConfirmation,
    MultisigTransaction,
    SafeLastStatus,
    SafeStatus,
)
from .factories import SafeMasterCopyFactory


class TestSafeEventsIndexer(SafeTestCaseMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.safe_events_indexer = SafeEventsIndexer(
            cls.ethereum_client, confirmations=0, blocks_to_reindex_again=0
        )
        cls.safe_tx_processor = SafeTxProcessor(cls.ethereum_client)

    def test_safe_events_indexer_provider(self):
        safe_events_indexer = SafeEventsIndexerProvider()
        self.assertEqual(safe_events_indexer.confirmations, 0)
        self.assertGreater(safe_events_indexer.blocks_to_reindex_again, 0)
        self.assertIsNotNone(SafeEventsIndexerProvider.instance)
        SafeEventsIndexerProvider.del_singleton()
        self.assertIsNone(getattr(SafeEventsIndexerProvider, "instance", None))

    def test_invalid_event(self):
        """
        AddedOwner event broke indexer on BSC. Same signature, but different number of indexed attributes
        """

        valid_event: LogReceipt = AttributeDict(
            {
                "address": "0x384f55D8BD4046461433A56bb87fe4aA615C0cc8",
                "blockHash": HexBytes(
                    "0x551a6e5ca972c453873898be696980d7ff65d27a6f80ddffab17591144c99e01"
                ),
                "blockNumber": 9205844,
                "data": "0x000000000000000000000000a1350318b2907ee0f6c8918eddc778a0b633e774",
                "logIndex": 0,
                "removed": False,
                "topics": [
                    HexBytes(
                        "0x9465fa0c962cc76958e6373a993326400c1c94f8be2fe3a952adfa7f60b2ea26"
                    )
                ],
                "transactionHash": HexBytes(
                    "0x7e4b2bb0ac5129552908e9c8433ea1746f76616188e8c3597a6bdce88d0b474c"
                ),
                "transactionIndex": 0,
                "transactionLogIndex": "0x0",
                "type": "mined",
            }
        )

        dangling_event: LogReceipt = AttributeDict(
            {
                "address": "0x1E44C806f1AfD4f420C10c8088f4e0388F066E7A",
                "topics": [
                    HexBytes(
                        "0x9465fa0c962cc76958e6373a993326400c1c94f8be2fe3a952adfa7f60b2ea26"
                    ),
                    HexBytes(
                        "0x00000000000000000000000020212521370dd2dde0b0e3ac25b65eb3e859d303"
                    ),
                ],
                "data": "0x",
                "blockNumber": 10129293,
                "transactionHash": HexBytes(
                    "0xc19ef099702fb9f7d7962925428683eff534e009210ef2cf23135f43962c192a"
                ),
                "transactionIndex": 89,
                "blockHash": HexBytes(
                    "0x6b41eac9177a1606e1a853adf3f3da018fcf476f7d217acb69b7d130bdfaf2c9"
                ),
                "logIndex": 290,
                "removed": False,
            }
        )

        # Dangling event topic is "supported"
        self.assertIn(
            dangling_event["topics"][0].hex(), self.safe_events_indexer.events_to_listen
        )

        # Dangling event cannot be decoded
        self.assertEqual(self.safe_events_indexer.decode_elements([dangling_event]), [])

        # Valid event is supported
        self.assertIn(
            valid_event["topics"][0].hex(), self.safe_events_indexer.events_to_listen
        )

        # Dangling event cannot be decoded
        expected_event = AttributeDict(
            {
                "args": AttributeDict(
                    {"owner": "0xa1350318b2907ee0f6c8918edDC778A0b633e774"}
                ),
                "event": "AddedOwner",
                "logIndex": 0,
                "transactionIndex": 0,
                "transactionHash": HexBytes(
                    "0x7e4b2bb0ac5129552908e9c8433ea1746f76616188e8c3597a6bdce88d0b474c"
                ),
                "address": "0x384f55D8BD4046461433A56bb87fe4aA615C0cc8",
                "blockHash": HexBytes(
                    "0x551a6e5ca972c453873898be696980d7ff65d27a6f80ddffab17591144c99e01"
                ),
                "blockNumber": 9205844,
            }
        )
        self.assertEqual(
            self.safe_events_indexer.decode_elements([valid_event]), [expected_event]
        )

    def test_safe_events_indexer(self):
        owner_account_1 = self.ethereum_test_account
        owners = [owner_account_1.address]
        threshold = 1
        to = NULL_ADDRESS
        data = b""
        fallback_handler = NULL_ADDRESS
        payment_token = NULL_ADDRESS
        payment = 0
        payment_receiver = NULL_ADDRESS
        initializer = HexBytes(
            self.safe_contract.functions.setup(
                owners,
                threshold,
                to,
                data,
                fallback_handler,
                payment_token,
                payment,
                payment_receiver,
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )
        initial_block_number = self.ethereum_client.current_block_number
        safe_l2_master_copy = SafeMasterCopyFactory(
            address=self.safe_contract.address,
            initial_block_number=initial_block_number,
            tx_block_number=initial_block_number,
            version="1.3.0",
            l2=True,
        )
        ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract(
            self.ethereum_test_account,
            self.safe_contract.address,
            initializer=initializer,
        )
        safe_address = ethereum_tx_sent.contract_address
        safe = Safe(safe_address, self.ethereum_client)
        safe_contract = get_safe_V1_3_0_contract(self.w3, safe_address)
        self.assertEqual(safe_contract.functions.VERSION().call(), "1.3.0")

        self.assertEqual(InternalTx.objects.count(), 0)
        self.assertEqual(InternalTxDecoded.objects.count(), 0)
        self.assertEqual(self.safe_events_indexer.start(), 2)
        self.assertEqual(InternalTxDecoded.objects.count(), 1)
        self.assertEqual(InternalTx.objects.count(), 2)  # Proxy factory and setup
        create_internal_tx = InternalTx.objects.filter(
            contract_address=safe_address
        ).get()
        setup_internal_tx = InternalTx.objects.filter(contract_address=None).get()

        self.assertEqual(create_internal_tx.trace_address, "1")
        self.assertEqual(create_internal_tx.tx_type, InternalTxType.CREATE.value)
        self.assertIsNone(create_internal_tx.call_type)
        self.assertTrue(create_internal_tx.is_relevant)

        self.assertEqual(setup_internal_tx.trace_address, "1,0")

        txs_decoded_queryset = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        self.assertEqual(SafeStatus.objects.count(), 1)
        safe_status = SafeStatus.objects.get()
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.master_copy, self.safe_contract.address)
        self.assertEqual(safe_status.owners, owners)
        self.assertEqual(safe_status.threshold, threshold)
        self.assertEqual(safe_status.nonce, 0)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertIsNone(safe_status.guard)
        self.assertEqual(MultisigTransaction.objects.count(), 0)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)

        # Add an owner but don't update the threshold (nonce: 0) --------------------------------------------------
        owner_account_2 = Account.create()
        data = HexBytes(
            self.safe_contract.functions.addOwnerWithThreshold(
                owner_account_2.address, 1
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, AddedOwner, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.assertEqual(InternalTx.objects.count(), 5)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one adding the owner
        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and addOwner
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(
            safe_status.owners, [owner_account_2.address, owner_account_1.address]
        )
        self.assertEqual(safe_status.nonce, 1)

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.owners, [owner_account_1.address])
        self.assertEqual(safe_status.nonce, 1)

        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(
            MultisigTransaction.objects.get().safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

        # Change threshold (nonce: 1) ------------------------------------------------------------------------------
        data = HexBytes(
            self.safe_contract.functions.changeThreshold(2).build_transaction(
                {"gas": 1, "gasPrice": 1}
            )["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedThreshold, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the threshold
        self.assertEqual(SafeStatus.objects.count(), 5)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and changeThreshold
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, 2)

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, 1)

        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 2)

        # Remove an owner and change threshold back to 1 (nonce: 2) --------------------------------------------------
        data = HexBytes(
            self.safe_contract.functions.removeOwner(
                SENTINEL_ADDRESS, owner_account_2.address, 1
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.sign(owner_account_2.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, RemovedOwner, ChangedThreshold, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 4)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one removing the owner
        self.assertEqual(SafeStatus.objects.count(), 8)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction, removeOwner and changeThreshold
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 1)
        self.assertEqual(safe_status.owners, [owner_account_1.address])

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Processed execTransaction and removeOwner
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 2)
        self.assertEqual(safe_status.owners, [owner_account_1.address])

        safe_status = SafeStatus.objects.sorted_by_mined()[
            2
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 2)
        self.assertCountEqual(
            safe_status.owners, [owner_account_1.address, owner_account_2.address]
        )

        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 4)

        # Enable module (nonce: 3) ---------------------------------------------------------------------
        module_address = Account.create().address
        data = HexBytes(
            self.safe_contract.functions.enableModule(module_address).build_transaction(
                {"gas": 1, "gasPrice": 1}
            )["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, EnabledModule, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one enabling the module
        self.assertEqual(SafeStatus.objects.count(), 10)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and enableModule
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 4)

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.nonce, 4)

        self.assertEqual(MultisigTransaction.objects.count(), 4)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 5)

        # Check SafeReceived (ether received) on Safe -----------------------------------------------------------------
        value = 1256
        self.ethereum_client.get_transaction_receipt(
            self.send_ether(safe_address, value)
        )
        # Process events: SafeReceived
        self.assertEqual(self.safe_events_indexer.start(), 1)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Check there's an ether transaction
        internal_tx_queryset = InternalTx.objects.filter(
            value=value,
            tx_type=InternalTxType.CALL.value,
            call_type=EthereumTxCallType.CALL.value,
        )
        self.assertTrue(internal_tx_queryset.exists())
        self.assertTrue(internal_tx_queryset.get().is_ether_transfer)

        # Set fallback handler (nonce: 4) --------------------------------------------------------------------------
        new_fallback_handler = Account.create().address
        data = HexBytes(
            self.safe_contract.functions.setFallbackHandler(
                new_fallback_handler
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedFallbackHandler, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the fallback handler
        self.assertEqual(SafeStatus.objects.count(), 12)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and setFallbackHandler
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.fallback_handler, new_fallback_handler)
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 5)

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 5)

        self.assertEqual(MultisigTransaction.objects.count(), 5)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 6)

        # Disable Module (nonce: 5) ----------------------------------------------------------------------------------
        data = HexBytes(
            self.safe_contract.functions.disableModule(
                SENTINEL_ADDRESS, module_address
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, DisabledModule, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one disabling the module
        self.assertEqual(SafeStatus.objects.count(), 14)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and disableModule
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 6)
        self.assertEqual(safe_status.enabled_modules, [])

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 6)
        self.assertEqual(safe_status.enabled_modules, [module_address])

        self.assertEqual(MultisigTransaction.objects.count(), 6)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 7)

        # ApproveHash (no nonce) ------------------------------------------------------------------------------------
        random_hash = self.w3.keccak(text="Get schwifty")
        tx = safe.contract.functions.approveHash(random_hash).build_transaction(
            {
                "from": owner_account_1.address,
                "nonce": self.ethereum_client.get_nonce_for_account(
                    owner_account_1.address
                ),
            }
        )
        tx = owner_account_1.sign_transaction(tx)
        self.w3.eth.send_raw_transaction(tx["rawTransaction"])
        # Process events: ApproveHash
        self.assertEqual(self.safe_events_indexer.start(), 1)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # No SafeStatus was added
        self.assertEqual(SafeStatus.objects.count(), 14)
        # Check a MultisigConfirmation was created
        self.assertTrue(
            MultisigConfirmation.objects.filter(
                multisig_transaction_hash=random_hash.hex()
            ).exists()
        )
        self.assertEqual(
            MultisigTransaction.objects.count(), 6
        )  # No MultisigTransaction was created
        self.assertEqual(
            MultisigConfirmation.objects.count(), 8
        )  # A MultisigConfirmation was created

        # Send ether (nonce: 6) ----------------------------------------------------------------------------------
        data = b""
        value = 122
        to = Account.create().address
        multisig_tx = safe.build_multisig_tx(to, value, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 2)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce
        self.assertEqual(SafeStatus.objects.count(), 15)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 7)
        self.assertTrue(
            InternalTx.objects.filter(value=value, to=to).get().is_ether_transfer
        )

        self.assertEqual(MultisigTransaction.objects.count(), 7)
        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 9)

        # Set guard (nonce: 7) INVALIDATES SAFE, as no more transactions can be done ---------------------------------
        guard_address = Account.create().address
        data = HexBytes(
            self.safe_contract.functions.setGuard(guard_address).build_transaction(
                {"gas": 1, "gasPrice": 1}
            )["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedGuard, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the guard
        self.assertEqual(SafeStatus.objects.count(), 17)
        safe_status = SafeStatus.objects.last_for_address(
            safe_address
        )  # Processed execTransaction and setGuard
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 8)
        self.assertEqual(safe_status.guard, guard_address)

        safe_status = SafeStatus.objects.sorted_by_mined()[
            1
        ]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 8)
        self.assertIsNone(safe_status.guard)

        # Check master copy did not change during the execution
        self.assertEqual(
            SafeStatus.objects.last_for_address(safe_address).master_copy,
            self.safe_contract.address,
        )

        self.assertEqual(
            MultisigTransaction.objects.order_by("-nonce")[0].safe_tx_hash,
            multisig_tx.safe_tx_hash.hex(),
        )
        expected_multisig_transactions = 8
        expected_multisig_confirmations = 10
        expected_safe_statuses = 17
        expected_internal_txs = 29
        expected_internal_txs_decoded = 18
        self.assertEqual(
            MultisigTransaction.objects.count(), expected_multisig_transactions
        )
        self.assertEqual(
            MultisigConfirmation.objects.count(), expected_multisig_confirmations
        )
        self.assertEqual(SafeStatus.objects.count(), expected_safe_statuses)
        self.assertEqual(InternalTx.objects.count(), expected_internal_txs)
        self.assertEqual(
            InternalTxDecoded.objects.count(), expected_internal_txs_decoded
        )

        # Event processing should be idempotent, so no changes must be done if everything is processed again
        self.assertTrue(self.safe_events_indexer._is_setup_indexed(safe_address))
        safe_l2_master_copy.tx_block_number = initial_block_number
        safe_l2_master_copy.save(update_fields=["tx_block_number"])
        self.assertEqual(
            self.safe_events_indexer.start(), 0
        )  # No new events are processed when reindexing
        InternalTxDecoded.objects.update(processed=False)
        SafeStatus.objects.all().delete()
        self.assertEqual(
            len(
                self.safe_tx_processor.process_decoded_transactions(
                    txs_decoded_queryset.all()
                )
            ),
            expected_internal_txs_decoded,
        )
        self.assertEqual(
            MultisigTransaction.objects.count(), expected_multisig_transactions
        )
        self.assertEqual(
            MultisigConfirmation.objects.count(), expected_multisig_confirmations
        )
        self.assertEqual(SafeStatus.objects.count(), expected_safe_statuses)
        self.assertEqual(InternalTx.objects.count(), expected_internal_txs)
        self.assertEqual(
            InternalTxDecoded.objects.count(), expected_internal_txs_decoded
        )
