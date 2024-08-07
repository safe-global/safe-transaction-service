from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Optional, OrderedDict, Sequence

from django.db import transaction

from eth_abi import decode as decode_abi
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import (
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
    get_safe_V1_1_1_contract,
    get_safe_V1_3_0_contract,
    get_safe_V1_4_1_contract,
)

from ..models import (
    EthereumBlock,
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    SafeMasterCopy,
    SafeRelevantTransaction,
)
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class SafeEventsIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls.get_new_instance()
        return cls.instance

    @classmethod
    def get_new_instance(cls) -> "SafeEventsIndexer":
        from django.conf import settings

        return SafeEventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeEventsIndexer(EventsIndexer):
    """
    Indexes Gnosis Safe L2 events
    """

    IGNORE_ADDRESSES_ON_LOG_FILTER = (
        True  # Search for logs in every address (like the ProxyFactory)
    )

    def __init__(self, *args, **kwargs):
        self.safe_setup_cache: Dict[ChecksumAddress, InternalTx] = {}
        super().__init__(*args, **kwargs)

    @cached_property
    def contract_events(self) -> List[ContractEvent]:
        """
        Safe v1.3.0 L2 Events
        ------------------
        event SafeMultiSigTransaction(
            address to,
            uint256 value,
            bytes data,
            Enum.Operation operation,
            uint256 safeTxGas,
            uint256 baseGas,
            uint256 gasPrice,
            address gasToken,
            address payable refundReceiver,
            bytes signatures,
            // We combine nonce, sender and threshold into one to avoid stack too deep
            // Dev note: additionalInfo should not contain `bytes`, as this complicates decoding
            bytes additionalInfo  // abi.encode(nonce, msg.sender, threshold);
        );

        event SafeModuleTransaction(
            address module,
            address to,
            uint256 value,
            bytes data,
            Enum.Operation operation,
        );

        event SafeSetup(
            address indexed initiator,
            address[] owners,
            uint256 threshold,
            address initializer,
            address fallbackHandler
        );

        event ApproveHash(
            bytes32 indexed approvedHash,
            address indexed owner
        );

        event SignMsg(
            bytes32 indexed msgHash
        );

        event ExecutionFailure(
            bytes32 txHash,
            uint256 payment
        );
        event ExecutionSuccess(
            bytes32 txHash,
            uint256 payment
        );

        event EnabledModule(address module);
        event DisabledModule(address module);
        event ExecutionFromModuleSuccess(address indexed module);
        event ExecutionFromModuleFailure(address indexed module);

        event AddedOwner(address owner);
        event RemovedOwner(address owner);
        event ChangedThreshold(uint256 threshold);

        # Incoming Ether
        event SafeReceived(
            address indexed sender,
            uint256 value
        );

        event ChangedFallbackHandler(address handler);
        event ChangedGuard(address guard);

        # ProxyFactory
        event ProxyCreation(GnosisSafeProxy proxy, address singleton);

        Safe v1.4.1 L2 Events
        ------------------
        event SafeMultiSigTransaction(
            address to,
            uint256 value,
            bytes data,
            Enum.Operation operation,
            uint256 safeTxGas,
            uint256 baseGas,
            uint256 gasPrice,
            address gasToken,
            address payable refundReceiver,
            bytes signatures,
            // We combine nonce, sender and threshold into one to avoid stack too deep
            // Dev note: additionalInfo should not contain `bytes`, as this complicates decoding
            bytes additionalInfo
        );

        event SafeModuleTransaction(
            address module,
            address to,
            uint256 value,
            bytes data,
            Enum.Operation operation,
        );

        event SafeSetup(
            address indexed initiator,
            address[] owners,
            uint256 threshold,
            address initializer,
            address fallbackHandler
        );

        event ApproveHash(
            bytes32 indexed approvedHash,
            address indexed owner
        );

        event SignMsg(
            bytes32 indexed msgHash
        );

        event ExecutionFailure(
            bytes32 indexed txHash,
            uint256 payment
        );

        event ExecutionSuccess(
            bytes32 indexed txHash,
            uint256 payment
        );

        event EnabledModule(address indexed module);
        event DisabledModule(address indexed module);
        event ExecutionFromModuleSuccess(address indexed module);
        event ExecutionFromModuleFailure(address indexed module);

        event AddedOwner(address indexed owner);
        event RemovedOwner(address indexed owner);
        event ChangedThreshold(uint256 threshold);

        # Incoming Ether
        event SafeReceived(
            address indexed sender,
            uint256 value
        );

        event ChangedFallbackHandler(address indexed handler);
        event ChangedGuard(address indexed guard);

        # ProxyFactory
        event ProxyCreation(GnosisSafeProxy indexed proxy, address singleton);

        :return: List of supported `ContractEvent`
        """
        proxy_factory_v1_4_1_contract = get_proxy_factory_V1_4_1_contract(
            self.ethereum_client.w3
        )
        proxy_factory_v1_3_0_contract = get_proxy_factory_V1_3_0_contract(
            self.ethereum_client.w3
        )
        safe_l2_v1_4_1_contract = get_safe_V1_4_1_contract(self.ethereum_client.w3)
        safe_l2_v1_3_0_contract = get_safe_V1_3_0_contract(self.ethereum_client.w3)
        safe_v1_1_1_contract = get_safe_V1_1_1_contract(self.ethereum_client.w3)
        return [
            safe_l2_v1_3_0_contract.events.SafeMultiSigTransaction(),
            safe_l2_v1_3_0_contract.events.SafeModuleTransaction(),
            safe_l2_v1_3_0_contract.events.SafeSetup(),
            safe_l2_v1_3_0_contract.events.ApproveHash(),
            safe_l2_v1_3_0_contract.events.SignMsg(),
            safe_l2_v1_4_1_contract.events.ExecutionFailure(),
            safe_l2_v1_3_0_contract.events.ExecutionFailure(),
            safe_l2_v1_4_1_contract.events.ExecutionSuccess(),
            safe_l2_v1_3_0_contract.events.ExecutionSuccess(),
            # Modules
            safe_l2_v1_4_1_contract.events.EnabledModule(),
            safe_l2_v1_3_0_contract.events.EnabledModule(),
            safe_l2_v1_4_1_contract.events.DisabledModule(),
            safe_l2_v1_3_0_contract.events.DisabledModule(),
            safe_l2_v1_3_0_contract.events.ExecutionFromModuleSuccess(),
            safe_l2_v1_3_0_contract.events.ExecutionFromModuleFailure(),
            # Owners
            safe_l2_v1_4_1_contract.events.AddedOwner(),
            safe_l2_v1_3_0_contract.events.AddedOwner(),
            safe_l2_v1_4_1_contract.events.RemovedOwner(),
            safe_l2_v1_3_0_contract.events.RemovedOwner(),
            safe_l2_v1_3_0_contract.events.ChangedThreshold(),
            # Incoming Ether
            safe_l2_v1_3_0_contract.events.SafeReceived(),
            # Changed FallbackHandler
            safe_l2_v1_4_1_contract.events.ChangedFallbackHandler(),
            safe_l2_v1_3_0_contract.events.ChangedFallbackHandler(),
            # Changed Guard
            safe_l2_v1_4_1_contract.events.ChangedGuard(),
            safe_l2_v1_3_0_contract.events.ChangedGuard(),
            # Change Master Copy
            safe_v1_1_1_contract.events.ChangedMasterCopy(),
            # Proxy creation
            proxy_factory_v1_4_1_contract.events.ProxyCreation(),
            proxy_factory_v1_3_0_contract.events.ProxyCreation(),
        ]

    @property
    def database_field(self):
        return "tx_block_number"

    @property
    def database_queryset(self):
        return SafeMasterCopy.objects.l2()

    def _is_setup_indexed(self, safe_address: ChecksumAddress):
        """
        Check if ``SafeSetup`` + ``ProxyCreation`` events were already processed. Makes indexing idempotent,
        as we modify the `trace_address` when processing `ProxyCreation`

        :param safe_address:
        :return: ``True`` if ``SafeSetup`` event was processed, ``False`` otherwise
        """
        return (
            safe_address in self.safe_setup_cache
            and self.safe_setup_cache[safe_address].contract_address is None
        ) or InternalTxDecoded.objects.filter(
            function_name="setup",
            internal_tx___from=safe_address,
            internal_tx__contract_address=None,
        ).exists()

    @transaction.atomic
    def decode_elements(self, *args) -> List[EventData]:
        return super().decode_elements(*args)

    @transaction.atomic
    def _process_decoded_element(
        self, decoded_element: EventData
    ) -> Optional[InternalTx]:
        safe_address = decoded_element["address"]
        event_name = decoded_element["event"]
        # As log
        log_index = decoded_element["logIndex"]
        trace_address = str(log_index)
        args = dict(decoded_element["args"])
        ethereum_tx_hash = HexBytes(decoded_element["transactionHash"])
        ethereum_tx_hash_hex = ethereum_tx_hash.hex()
        ethereum_block = EthereumBlock.objects.values("number", "timestamp").get(
            txs=ethereum_tx_hash
        )
        logger.debug(
            "[%s] %s - tx-hash=%s - Processing event %s",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
            decoded_element,
        )

        internal_tx = InternalTx(
            ethereum_tx_id=ethereum_tx_hash,
            timestamp=ethereum_block["timestamp"],
            block_number=ethereum_block["number"],
            _from=safe_address,
            gas=50000,
            data=b"",
            to=NULL_ADDRESS,  # It should be Master copy address but we cannot detect it
            value=0,
            gas_used=50000,
            contract_address=None,
            code=None,
            output=None,
            refund_address=None,
            tx_type=InternalTxType.CALL.value,
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            trace_address=trace_address,
            error=None,
        )
        child_internal_tx: Optional[InternalTx] = None  # For Ether transfers
        internal_tx_decoded = InternalTxDecoded(
            internal_tx=internal_tx,
            function_name="",
            arguments=args,
        )
        if event_name == "ProxyCreation":
            # Should be the 2nd event to be indexed, after `SafeSetup`
            safe_address = args.pop("proxy")

            if self._is_setup_indexed(safe_address):
                internal_tx = None
            else:
                new_trace_address = f"{trace_address},0"
                to = args.pop("singleton")

                # Try to update InternalTx created by SafeSetup (if Safe was created using the ProxyFactory) with
                # the master copy used. Without tracing it cannot be detected otherwise
                InternalTx.objects.filter(
                    contract_address=safe_address, decoded_tx__function_name="setup"
                ).update(to=to, contract_address=None, trace_address=new_trace_address)

                setup_internal_tx = self.safe_setup_cache[safe_address]
                setup_internal_tx.to = to
                setup_internal_tx.contract_address = None
                setup_internal_tx.trace_address = new_trace_address

                # Add creation internal tx. _from is the address of the proxy instead of the safe_address
                internal_tx.contract_address = safe_address
                internal_tx.tx_type = InternalTxType.CREATE.value
                internal_tx.call_type = None
                internal_tx_decoded = None
        elif event_name == "SafeSetup":
            # Should be the 1st event to be indexed, unless custom `to` and `data` are set
            if self._is_setup_indexed(safe_address):
                internal_tx = None
            else:
                # Usually ProxyCreation is called before SafeSetup, but it can be the opposite if someone
                # creates a Safe and configure it in the next transaction. Remove it if that's the case
                InternalTx.objects.filter(contract_address=safe_address).delete()
                internal_tx.contract_address = safe_address
                internal_tx_decoded.function_name = "setup"
                args["payment"] = 0
                args["paymentReceiver"] = NULL_ADDRESS
                args["_threshold"] = args.pop("threshold")
                args["_owners"] = args.pop("owners")
                self.safe_setup_cache[safe_address] = internal_tx
        elif event_name == "SafeMultiSigTransaction":
            internal_tx_decoded.function_name = "execTransaction"
            data = HexBytes(args["data"])
            args["data"] = data.hex()
            args["signatures"] = HexBytes(args["signatures"]).hex()
            additional_info = HexBytes(
                internal_tx_decoded.arguments.pop("additionalInfo")
            )
            try:
                args["nonce"], args["sender"], args["threshold"] = decode_abi(
                    ["uint256", "address", "uint256"],
                    additional_info,
                )
            except DecodingError:
                logger.error(
                    "[%s] %s - tx-hash=%s - Cannot decode SafeMultiSigTransaction with additionalInfo=%s",
                    safe_address,
                    event_name,
                    ethereum_tx_hash_hex,
                    additional_info.hex(),
                )
            if args["value"] and not data:  # Simulate ether transfer
                child_internal_tx = InternalTx(
                    ethereum_tx_id=ethereum_tx_hash,
                    timestamp=ethereum_block["timestamp"],
                    block_number=ethereum_block["number"],
                    _from=safe_address,
                    gas=23000,
                    data=b"",
                    to=args["to"],
                    value=args["value"],
                    gas_used=23000,
                    contract_address=None,
                    code=None,
                    output=None,
                    refund_address=None,
                    tx_type=InternalTxType.CALL.value,
                    call_type=EthereumTxCallType.CALL.value,
                    trace_address=f"{trace_address},0",
                    error=None,
                )
        elif event_name == "SafeModuleTransaction":
            internal_tx_decoded.function_name = "execTransactionFromModule"
            args["data"] = HexBytes(args["data"]).hex()
        elif event_name == "ApproveHash":
            internal_tx_decoded.function_name = "approveHash"
            args["hashToApprove"] = args.pop("approvedHash").hex()
        elif event_name == "EnabledModule":
            internal_tx_decoded.function_name = "enableModule"
        elif event_name == "DisabledModule":
            internal_tx_decoded.function_name = "disableModule"
        elif event_name == "AddedOwner":
            internal_tx_decoded.function_name = "addOwnerWithThreshold"
            args["_threshold"] = None
        elif event_name == "RemovedOwner":
            internal_tx_decoded.function_name = "removeOwner"
            args["_threshold"] = None
        elif event_name == "ChangedThreshold":
            internal_tx_decoded.function_name = "changeThreshold"
            args["_threshold"] = args.pop("threshold")
        elif event_name == "ChangedFallbackHandler":
            internal_tx_decoded.function_name = "setFallbackHandler"
        elif event_name == "ChangedGuard":
            internal_tx_decoded.function_name = "setGuard"
        elif event_name == "SafeReceived":  # Received ether
            internal_tx.call_type = EthereumTxCallType.CALL.value
            internal_tx._from = args["sender"]
            internal_tx.to = safe_address
            internal_tx.value = args["value"]
            internal_tx_decoded = None
        elif event_name == "ChangedMasterCopy":
            internal_tx_decoded.function_name = "changeMasterCopy"
            internal_tx_decoded.arguments = {
                "_masterCopy": args.get("masterCopy") or args.get("singleton")
            }
        else:
            # 'SignMsg', 'ExecutionFailure', 'ExecutionSuccess',
            # 'ExecutionFromModuleSuccess', 'ExecutionFromModuleFailure'
            internal_tx_decoded = None

        internal_txs = []
        internal_txs_decoded = []
        safe_relevant_txs = []
        if internal_tx:
            internal_txs.append(internal_tx)
            if internal_tx.is_ether_transfer:
                # Store Incoming Ether Transfers as relevant transactions for a Safe
                safe_relevant_txs.append(
                    SafeRelevantTransaction(
                        ethereum_tx_id=ethereum_tx_hash,
                        safe=safe_address,
                        timestamp=ethereum_block["timestamp"],
                    )
                )
            if child_internal_tx:
                internal_txs.append(child_internal_tx)
            if internal_tx_decoded:
                internal_txs_decoded.append(internal_tx_decoded)

        logger.debug(
            "[%s] %s - tx-hash=%s - Processed event",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
        )

        return internal_txs, internal_txs_decoded, safe_relevant_txs

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> List[Any]:
        """
        Process all events found by `find_relevant_elements`

        :param log_receipts: Events to store in database
        :return: List of events already stored in database
        """
        if not log_receipts:
            return []

        logger.debug("Excluding events processed recently")
        # Ignore already processed events
        not_processed_log_receipts = [
            log_receipt
            for log_receipt in log_receipts
            if not self.element_already_processed_checker.is_processed(
                log_receipt["transactionHash"],
                log_receipt["blockHash"],
                log_receipt["logIndex"],
            )
        ]
        logger.debug("Decoding `log_receipts` of the events")
        decoded_elements: List[EventData] = self.decode_elements(
            not_processed_log_receipts
        )
        logger.debug("Decoded `log_receipts` of the events")
        tx_hashes = OrderedDict.fromkeys(
            [event["transactionHash"] for event in not_processed_log_receipts]
        ).keys()
        logger.debug("Prefetching and storing %d ethereum txs", len(tx_hashes))
        self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug("End prefetching and storing of ethereum txs")
        logger.debug("Processing %d decoded events", len(decoded_elements))
        internal_txs_to_insert = []
        internal_txs_decoded_to_insert = []
        safe_relevant_txs_to_insert = []
        for decoded_element in decoded_elements:
            internal_txs, internal_txs_decoded, safe_relevant_txs = (
                self._process_decoded_element(decoded_element)
            )
            internal_txs_to_insert.extend(internal_txs)
            internal_txs_decoded_to_insert.extend(internal_txs_decoded)
            safe_relevant_txs_to_insert.extend(safe_relevant_txs)
        logger.debug("End processing %d decoded events", len(decoded_elements))

        logger.info("Inserting %d elements on database", len(internal_txs_to_insert))
        InternalTx.objects.filter(ethereum_tx_id__in=tx_hashes).delete()
        InternalTx.objects.bulk_create(internal_txs_to_insert)
        # If we use `ignore_conflicts`, things are not inserted
        InternalTxDecoded.objects.bulk_create(
            internal_txs_decoded_to_insert, ignore_conflicts=True
        )
        SafeRelevantTransaction.objects.bulk_create(
            safe_relevant_txs_to_insert, ignore_conflicts=True
        )
        self.safe_setup_cache.clear()
        logger.info(
            "End inserting %d elements on database", len(internal_txs_to_insert)
        )

        logger.debug("Marking events as processed")
        for log_receipt in not_processed_log_receipts:
            self.element_already_processed_checker.mark_as_processed(
                log_receipt["transactionHash"],
                log_receipt["blockHash"],
                log_receipt["logIndex"],
            )
        logger.debug("Marked events as processed")

        return internal_txs_to_insert
