from django.test import TestCase

from eth_account import Account
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.types import LogReceipt

from gnosis.eth.constants import NULL_ADDRESS, SENTINEL_ADDRESS
from gnosis.eth.contracts import get_safe_V1_3_0_contract, get_safe_V1_4_1_contract
from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..indexers import SafeEventsIndexer, SafeEventsIndexerProvider
from ..indexers.tx_processor import SafeTxProcessor
from ..models import (
    EthereumTx,
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    MultisigConfirmation,
    MultisigTransaction,
    SafeLastStatus,
    SafeStatus,
)
from .factories import EthereumTxFactory, SafeMasterCopyFactory
from .mocks.mocks_safe_events_indexer import safe_events_mock


class TestSafeEventsIndexerV1_4_1(SafeTestCaseMixin, TestCase):
    def setUp(self) -> None:
        self.safe_events_indexer = SafeEventsIndexer(
            self.ethereum_client, confirmations=0, blocks_to_reindex_again=0
        )
        self.safe_tx_processor = SafeTxProcessor(self.ethereum_client, None)

    def tearDown(self) -> None:
        SafeEventsIndexerProvider.del_singleton()

    @property
    def safe_contract_version(self) -> str:
        return "1.4.1"

    @property
    def safe_contract(self):
        """
        :return: Last Safe Contract available
        """
        return self.safe_contract_V1_4_1

    def get_safe_contract(self, w3: Web3, address: ChecksumAddress):
        """
        :return: Last Safe Contract available
        """
        return get_safe_V1_4_1_contract(w3, address=address)

    def test_safe_events_indexer_provider(self):
        safe_events_indexer = SafeEventsIndexerProvider()
        self.assertEqual(safe_events_indexer.confirmations, 0)
        self.assertGreater(safe_events_indexer.blocks_to_reindex_again, 0)
        self.assertIsNotNone(SafeEventsIndexerProvider.instance)
        SafeEventsIndexerProvider.del_singleton()
        self.assertIsNone(getattr(SafeEventsIndexerProvider, "instance", None))

    def test_invalid_event(self):
        """
        Events with same name and types, but different indexed elements can break the indexer
        We will test the expected:

        event ExecutionSuccess(
            bytes32 txHash,
            uint256 payment
        );

        With the made out:
        event ExecutionSuccess(
            bytes32 indexed txHash,
            uint256 indexed payment
        );
        """

        valid_event: LogReceipt = AttributeDict(
            {
                "address": "0xE618d8147210d45ffCBd2E3b33DD44252a43fF76",
                "topics": [
                    HexBytes(
                        "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e"
                    )
                ],
                "data": HexBytes(
                    "0x55e61223bfe56101c8243067945cf90da23f0e0a3409eac65dc6e8852833cf440000000000000000000000000000000000000000000000000000000000000000"
                ),
                "blockNumber": 9727973,
                "transactionHash": HexBytes(
                    "0x9afccb1cf5498ae564b5589bf4bbf0b29b486f52952d1270dd51702ed2e29ff9"
                ),
                "transactionIndex": 50,
                "blockHash": HexBytes(
                    "0x3b2a9816f9b4280dc0190f1aafb910c99efbbf836e1865ab068ecbf6c0402fa7"
                ),
                "logIndex": 129,
                "removed": False,
            }
        )

        dangling_event: LogReceipt = AttributeDict(
            {
                "address": "0xE618d8147210d45ffCBd2E3b33DD44252a43fF76",
                "topics": [
                    HexBytes(
                        "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e"
                    ),
                    HexBytes(
                        "0x55e61223bfe56101c8243067945cf90da23f0e0a3409eac65dc6e8852833cf44"
                    ),
                    HexBytes(
                        "0x0000000000000000000000000000000000000000000000000000000000000000"
                    ),
                ],
                "data": HexBytes("0x"),
                "blockNumber": 9727973,
                "transactionHash": HexBytes(
                    "0x9afccb1cf5498ae564b5589bf4bbf0b29b486f52952d1270dd51702ed2e29ff9"
                ),
                "transactionIndex": 50,
                "blockHash": HexBytes(
                    "0x3b2a9816f9b4280dc0190f1aafb910c99efbbf836e1865ab068ecbf6c0402fa7"
                ),
                "logIndex": 129,
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

        # Dangling event cannot be decoded, but valid event is
        expected_event = AttributeDict(
            {
                "args": AttributeDict(
                    {
                        "txHash": b"U\xe6\x12#\xbf\xe5a\x01\xc8$0g\x94\\\xf9\r\xa2?\x0e\n4\t\xea\xc6]\xc6\xe8\x85(3\xcfD",
                        "payment": 0,
                    }
                ),
                "event": "ExecutionSuccess",
                "logIndex": 129,
                "transactionIndex": 50,
                "transactionHash": HexBytes(
                    "0x9afccb1cf5498ae564b5589bf4bbf0b29b486f52952d1270dd51702ed2e29ff9"
                ),
                "address": "0xE618d8147210d45ffCBd2E3b33DD44252a43fF76",
                "blockHash": HexBytes(
                    "0x3b2a9816f9b4280dc0190f1aafb910c99efbbf836e1865ab068ecbf6c0402fa7"
                ),
                "blockNumber": 9727973,
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
        initial_block_number = self.ethereum_client.current_block_number + 1
        safe_l2_master_copy = SafeMasterCopyFactory(
            address=self.safe_contract.address,
            initial_block_number=initial_block_number,
            tx_block_number=initial_block_number,
            version=self.safe_contract_version,
            l2=True,
        )
        ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract_with_nonce(
            self.ethereum_test_account,
            self.safe_contract.address,
            initializer=initializer,
        )
        safe_address = ethereum_tx_sent.contract_address
        safe = Safe(safe_address, self.ethereum_client)
        safe_contract = self.get_safe_contract(self.w3, safe_address)
        self.assertEqual(
            safe_contract.functions.VERSION().call(), self.safe_contract_version
        )

        self.assertEqual(InternalTx.objects.count(), 0)
        self.assertEqual(InternalTxDecoded.objects.count(), 0)
        self.assertEqual(self.safe_events_indexer.start(), (2, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (3, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (3, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (4, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (3, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (1, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (3, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (3, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (1, 1))
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
        self.assertEqual(self.safe_events_indexer.start(), (2, 1))
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

        # Set guard (nonce: 7) ---------------------------------
        guard_address = self.deploy_example_guard()
        data = HexBytes(
            self.safe_contract.functions.setGuard(guard_address).build_transaction(
                {"gas": 1, "gasPrice": 1}
            )["data"]
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedGuard, ExecutionSuccess
        # 2 blocks will be processed due to the guard deployment
        self.assertEqual(self.safe_events_indexer.start(), (3, 2))
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
        blocks_processed = (
            self.safe_events_indexer.ethereum_client.current_block_number
            - initial_block_number
            + 1
        )
        self.assertEqual(
            self.safe_events_indexer.start(), (0, blocks_processed)
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

    def test_element_already_processed_checker(self):
        # SafeEventsIndexer does not use bulk saving into database,
        # so mark_as_processed is just a optimization but not critical

        # Create transaction in db so not fetching of transaction is needed
        for safe_event in safe_events_mock:
            tx_hash = safe_event["transactionHash"]
            block_hash = safe_event["blockHash"]
            if not EthereumTx.objects.filter(tx_hash=tx_hash).exists():
                EthereumTxFactory(tx_hash=tx_hash, block__block_hash=block_hash)

        # After the first processing transactions will be cached to prevent reprocessing
        processed_element_cache = (
            self.safe_events_indexer.element_already_processed_checker._processed_element_cache
        )
        self.assertEqual(len(processed_element_cache), 0)
        self.assertEqual(
            len(self.safe_events_indexer.process_elements(safe_events_mock)), 28
        )
        self.assertEqual(len(processed_element_cache), 28)

        # Transactions are cached and will not be reprocessed
        self.assertEqual(
            len(self.safe_events_indexer.process_elements(safe_events_mock)), 0
        )
        self.assertEqual(
            len(self.safe_events_indexer.process_elements(safe_events_mock)), 0
        )

        # Even if we empty the cache, events will not be reprocessed again
        self.safe_events_indexer.element_already_processed_checker.clear()
        self.assertEqual(
            len(self.safe_events_indexer.process_elements(safe_events_mock)), 0
        )

    def test_auto_adjust_block_limit(self):
        self.safe_events_indexer.block_process_limit = 1
        self.safe_events_indexer.block_process_limit_max = 5
        with self.safe_events_indexer.auto_adjust_block_limit(100, 100):
            pass

        self.assertEqual(self.safe_events_indexer.block_process_limit, 2)

        with self.safe_events_indexer.auto_adjust_block_limit(100, 101):
            pass
        self.assertEqual(self.safe_events_indexer.block_process_limit, 4)

        # Check it cannot go further than `block_process_limit_max`
        with self.safe_events_indexer.auto_adjust_block_limit(100, 103):
            pass
        self.assertEqual(self.safe_events_indexer.block_process_limit, 5)

        with self.safe_events_indexer.auto_adjust_block_limit(100, 104):
            pass
        self.assertEqual(self.safe_events_indexer.block_process_limit, 5)


class TestSafeEventsIndexerV1_3_0(TestSafeEventsIndexerV1_4_1):
    @property
    def safe_contract_version(self) -> str:
        return "1.3.0"

    @property
    def safe_contract(self):
        """
        :return: Last Safe Contract available
        """
        return self.safe_contract_V1_3_0

    def get_safe_contract(self, w3: Web3, address: ChecksumAddress):
        """
        :return: Last Safe Contract available
        """
        return get_safe_V1_3_0_contract(w3, address=address)
