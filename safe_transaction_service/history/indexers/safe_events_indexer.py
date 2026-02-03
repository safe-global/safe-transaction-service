import datetime
from collections import OrderedDict
from collections.abc import Sequence
from functools import cached_property
from logging import getLogger

from django.conf import settings

from eth_abi import decode as decode_abi
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.contracts import (
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
    get_safe_V1_1_1_contract,
    get_safe_V1_3_0_contract,
    get_safe_V1_4_1_contract,
    get_safe_V1_5_0_contract,
)
from safe_eth.util.util import to_0x_hex_str
from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt, TxData, TxReceipt

from ..models import (
    EthereumBlock,
    EthereumTx,
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    SafeContract,
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
        return SafeEventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeEventsIndexer(EventsIndexer):
    """
    Indexes Safe L2 events
    """

    IGNORE_ADDRESSES_ON_LOG_FILTER = (
        True  # Search for logs in every address (like the ProxyFactory)
    )

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "eth_zksync_compatible_network", settings.ETH_ZKSYNC_COMPATIBLE_NETWORK
        )
        kwargs.setdefault("ignored_initiators", settings.ETH_EVENTS_IGNORED_INITIATORS)
        kwargs.setdefault("ignored_to", settings.ETH_EVENTS_IGNORED_TO)

        self.eth_zksync_compatible_network = kwargs["eth_zksync_compatible_network"]
        self.ignored_initiators = kwargs["ignored_initiators"]
        self.ignored_to = kwargs["ignored_to"]
        self.conditional_indexing_enabled = bool(
            self.ignored_initiators or self.ignored_to
        )
        # Cache timestamp for block hashes
        self.block_hashes_with_timestamp: dict[bytes, datetime.datetime] = {}
        super().__init__(*args, **kwargs)

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> list[InternalTx]:
        """
        Override to filter events by tx._from and tx.to when conditional indexing is enabled.
        This avoids storing EthereumTx in database for blocklisted addresses.
        """
        if not log_receipts:
            return []

        if not self.conditional_indexing_enabled:
            # No blocklist configured, use standard flow
            return super().process_elements(log_receipts)

        return self._process_elements_with_conditional_indexing(log_receipts)

    def _process_elements_with_conditional_indexing(
        self, log_receipts: Sequence[LogReceipt]
    ) -> list[InternalTx]:
        # --- Conditional indexing enabled ---
        logger.debug("Conditional indexing: filtering events by tx._from and tx.to")

        # 1. Filter already processed log receipts and normalize tx hashes once
        not_processed_log_receipts: list[LogReceipt] = []
        not_processed_tx_hashes_by_index: list[bytes] = []
        for log_receipt in log_receipts:
            if self.element_already_processed_checker.is_processed(
                log_receipt["transactionHash"],
                log_receipt["blockHash"],
                log_receipt["logIndex"],
            ):
                continue
            not_processed_log_receipts.append(log_receipt)
            not_processed_tx_hashes_by_index.append(
                HexBytes(log_receipt["transactionHash"])
            )

        if not not_processed_log_receipts:
            return []

        # 2. Get unique tx_hashes preserving order
        tx_hashes = list(OrderedDict.fromkeys(not_processed_tx_hashes_by_index).keys())

        # 3. Check DB for existing txs
        db_txs: dict[bytes, EthereumTx] = {
            HexBytes(tx.tx_hash): tx
            for tx in EthereumTx.objects.filter(tx_hash__in=tx_hashes).exclude(
                block=None
            )
        }
        logger.debug("Conditional indexing: found %d existing txs in DB", len(db_txs))

        # 4. Fetch missing txs from RPC (without receipts - we'll fetch those only for allowed txs)
        missing_hashes = [tx_hash for tx_hash in tx_hashes if tx_hash not in db_txs]
        logger.debug(
            "Conditional indexing: fetching %d missing txs from RPC",
            len(missing_hashes),
        )
        fetched_txs = self._fetch_txs(missing_hashes)

        # 5. Filter by _from and to (blocklist check)
        allowed_tx_hashes: set[bytes] = set()

        # Check existing DB txs
        for tx_hash, db_tx in db_txs.items():
            if db_tx._from in self.ignored_initiators:
                logger.debug(
                    "Conditional indexing: filtering existing tx %s from blocklisted initiator %s",
                    to_0x_hex_str(tx_hash),
                    db_tx._from,
                )
            elif db_tx.to in self.ignored_to:
                logger.debug(
                    "Conditional indexing: filtering existing tx %s to blocklisted address %s",
                    to_0x_hex_str(tx_hash),
                    db_tx.to,
                )
            else:
                allowed_tx_hashes.add(tx_hash)

        # Check fetched txs, filter allowed ones
        allowed_fetched_txs: list[TxData] = []
        for tx in fetched_txs:
            tx_hash = HexBytes(tx["hash"])
            tx_from = tx.get("from")
            tx_to = tx.get("to")
            if tx_from in self.ignored_initiators:
                logger.debug(
                    "Conditional indexing: filtering tx %s from blocklisted initiator %s",
                    to_0x_hex_str(tx_hash),
                    tx_from,
                )
            elif tx_to in self.ignored_to:
                logger.debug(
                    "Conditional indexing: filtering tx %s to blocklisted address %s",
                    to_0x_hex_str(tx_hash),
                    tx_to,
                )
            else:
                allowed_fetched_txs.append(tx)
                allowed_tx_hashes.add(tx_hash)

        logger.debug(
            "Conditional indexing: %d/%d txs allowed after filtering",
            len(allowed_tx_hashes),
            len(tx_hashes),
        )

        # 6. Filter log_receipts to only allowed txs
        filtered_log_receipts = [
            log_receipt
            for log_receipt, tx_hash in zip(
                not_processed_log_receipts,
                not_processed_tx_hashes_by_index,
                strict=False,
            )
            if tx_hash in allowed_tx_hashes
        ]

        # 7. Decode elements BEFORE creating EthereumTx
        decoded_elements = self.decode_elements(filtered_log_receipts)

        # 8. Filter to only events that will be processed
        processable_events = self._get_processable_events(decoded_elements)

        # 9. Get tx_hashes only from processable events
        tx_hashes_to_create = list(
            OrderedDict.fromkeys(
                HexBytes(event["transactionHash"]) for event in processable_events
            ).keys()
        )

        logger.debug(
            "Conditional indexing: %d/%d txs have processable events",
            len(tx_hashes_to_create),
            len(allowed_tx_hashes),
        )

        # 10. Filter allowed_fetched_txs to only those with processable events
        allowed_fetched_txs_filtered = [
            tx
            for tx in allowed_fetched_txs
            if HexBytes(tx["hash"]) in tx_hashes_to_create
        ]

        # 11. Fetch receipts and store ONLY for txs with processable events
        if allowed_fetched_txs_filtered:
            number_allowed_txs_inserted = self._fetch_receipts_and_store(
                allowed_fetched_txs_filtered
            )
            logger.debug(
                "Conditional indexing: %d txs with processable events inserted",
                number_allowed_txs_inserted,
            )

        # 12. Process only the processable events
        # (filtering already done by _get_processable_events)
        processed_elements = self._process_decoded_elements(processable_events)

        # 13. Mark ALL original receipts as processed (so we don't re-fetch blocked ones)
        for log_receipt in not_processed_log_receipts:
            self.element_already_processed_checker.mark_as_processed(
                log_receipt["transactionHash"],
                log_receipt["blockHash"],
                log_receipt["logIndex"],
            )

        return processed_elements

    def _get_processable_events(
        self, decoded_elements: list[EventData]
    ) -> list[EventData]:
        """
        Filter decoded elements to only those that will be processed.
        When conditional indexing is enabled, non-creation events are only
        processed if their Safe exists in SafeContract table or is created
        in the same batch.

        :param decoded_elements: All decoded events
        :return: Filtered list of events that will actually be processed
        """
        if not self.conditional_indexing_enabled:
            return decoded_elements

        # Single iteration: separate creation/non-creation events and collect addresses
        creation_events = []
        non_creation_events = []
        non_creation_addresses = set()
        creation_addresses = set()

        for element in decoded_elements:
            if element["event"] in ("SafeSetup", "ProxyCreation"):
                creation_events.append(element)
                if element["event"] == "SafeSetup":
                    creation_addresses.add(element["address"])
                else:
                    proxy_address = element["args"].get("proxy")
                    if proxy_address:
                        creation_addresses.add(proxy_address)
            else:
                non_creation_events.append(element)
                non_creation_addresses.add(element["address"])

        # Filter non-creation events by SafeContract existence
        if non_creation_addresses:
            existing_addresses = SafeContract.objects.get_existing_addresses(
                non_creation_addresses
            )
            allowed_addresses = set(existing_addresses) | creation_addresses
            logger.debug(
                "Conditional indexing: %d/%d Safes found in database for event filtering "
                "(%d created in batch)",
                len(existing_addresses),
                len(non_creation_addresses),
                len(creation_addresses),
            )
            filtered_non_creation = [
                element
                for element in non_creation_events
                if element["address"] in allowed_addresses
            ]
        else:
            filtered_non_creation = []

        # Return: all creation events + filtered non-creation events
        return creation_events + filtered_non_creation

    @cached_property
    def contract_events(self) -> list[ContractEvent]:
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

        Safe v1.5.0 L2 Events
        ProxyCreationL2 or ChainSpecificProxyCreationL2 are not considered here because tracking ProxyCreation is enough.
        ------------------
        event ChangedModuleGuard(address indexed moduleGuard);

        :return: List of supported `ContractEvent`
        """
        proxy_factory_v1_4_1_contract = get_proxy_factory_V1_4_1_contract(
            self.ethereum_client.w3
        )
        proxy_factory_v1_3_0_contract = get_proxy_factory_V1_3_0_contract(
            self.ethereum_client.w3
        )
        safe_l2_v1_5_0_contract = get_safe_V1_5_0_contract(self.ethereum_client.w3)
        safe_l2_v1_4_1_contract = get_safe_V1_4_1_contract(self.ethereum_client.w3)
        safe_l2_v1_3_0_contract = get_safe_V1_3_0_contract(self.ethereum_client.w3)
        safe_v1_1_1_contract = get_safe_V1_1_1_contract(self.ethereum_client.w3)

        return [
            event
            for event in (
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
                (
                    safe_l2_v1_3_0_contract.events.SafeReceived()
                    if not self.eth_zksync_compatible_network
                    else None
                ),  # zkSync networks deal with native transfers as ERC20, duplicating them during indexing
                # Changed FallbackHandler
                safe_l2_v1_4_1_contract.events.ChangedFallbackHandler(),
                safe_l2_v1_3_0_contract.events.ChangedFallbackHandler(),
                # Changed Guard
                safe_l2_v1_4_1_contract.events.ChangedGuard(),
                safe_l2_v1_3_0_contract.events.ChangedGuard(),
                # Change Module Guard
                safe_l2_v1_5_0_contract.events.ChangedModuleGuard(),
                # Change Master Copy
                safe_v1_1_1_contract.events.ChangedMasterCopy(),
                # Proxy creation
                proxy_factory_v1_4_1_contract.events.ProxyCreation(),
                proxy_factory_v1_3_0_contract.events.ProxyCreation(),
            )
            if event
        ]

    @property
    def database_field(self):
        return "tx_block_number"

    @property
    def database_queryset(self):
        return SafeMasterCopy.objects.l2()

    def _get_internal_tx_from_decoded_element(
        self, decoded_element: EventData, **kwargs
    ) -> InternalTx:
        """
        Creates an InternalTx instance from the given decoded_event.
        Allows overriding object parameters with additional keyword arguments.

        :param decoded_element:
        :param kwargs:
        :return:
        """
        ethereum_block_number = decoded_element["blockNumber"]
        safe_address = decoded_element["address"]
        ethereum_tx_hash = HexBytes(decoded_element["transactionHash"])
        log_index = decoded_element["logIndex"]
        trace_address = str(log_index)
        block_hash = decoded_element["blockHash"]

        try:
            ethereum_block_timestamp = self.block_hashes_with_timestamp[block_hash]
        except KeyError:
            logger.error(
                "Getting block %s timestamp from database, not expected as it should have been prefetched",
                to_0x_hex_str(block_hash),
            )
            ethereum_block_timestamp = EthereumBlock.objects.get_timestamp_by_hash(
                block_hash
            )

        # Setting default values
        internal_tx = InternalTx(
            ethereum_tx_id=ethereum_tx_hash,
            timestamp=ethereum_block_timestamp,
            block_number=ethereum_block_number,
            _from=safe_address,
            gas=50000,
            data=b"",
            to=decoded_element["args"].get("to", NULL_ADDRESS),
            value=decoded_element["args"].get("value", 0),
            gas_used=50000,
            contract_address=None,
            code=None,
            output=None,
            refund_address=None,
            tx_type=InternalTxType.CALL.value,
            call_type=EthereumTxCallType.CALL.value,
            trace_address=trace_address,
            error=None,
        )
        # Overriding passed keys
        for key, value in kwargs.items():
            if hasattr(internal_tx, key):
                setattr(internal_tx, key, value)
            else:
                raise AttributeError(f"Invalid attribute {key} for InternalTx")

        return internal_tx

    def _process_decoded_element(
        self, decoded_element: EventData
    ) -> list[InternalTx | InternalTxDecoded | SafeRelevantTransaction]:
        safe_address = decoded_element["address"]
        event_name = decoded_element["event"]
        # As log
        log_index = decoded_element["logIndex"]
        trace_address = str(log_index)
        args = dict(decoded_element["args"])
        ethereum_tx_hash = HexBytes(decoded_element["transactionHash"])
        ethereum_tx_hash_hex = to_0x_hex_str(ethereum_tx_hash)

        logger.debug(
            "[%s] %s - tx-hash=%s - Processing event %s",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
            decoded_element,
        )

        internal_tx = self._get_internal_tx_from_decoded_element(
            decoded_element,
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            to=NULL_ADDRESS,
            value=0,
        )
        child_internal_tx: InternalTx | None = None  # For Ether transfers
        internal_tx_decoded = InternalTxDecoded(
            internal_tx=internal_tx,
            function_name="",
            arguments=args,
            safe_address=internal_tx._from,  # Denormalized for efficient querying
        )

        if event_name == "ProxyCreation" or event_name == "SafeSetup":
            # Will ignore these events because were indexed in process_safe_creation_events
            internal_tx = None
            internal_tx_decoded = None
        elif event_name == "SafeMultiSigTransaction":
            internal_tx_decoded.function_name = "execTransaction"
            data = HexBytes(args["data"])
            args["data"] = to_0x_hex_str(data)
            args["signatures"] = to_0x_hex_str(HexBytes(args["signatures"]))
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
                    to_0x_hex_str(additional_info),
                )
            if args["value"] and not data:  # Simulate ether transfer
                child_internal_tx = self._get_internal_tx_from_decoded_element(
                    decoded_element,
                    gas=23000,
                    gas_used=23000,
                    trace_address=f"{trace_address},0",
                )

        elif event_name == "SafeModuleTransaction":
            internal_tx_decoded.function_name = "execTransactionFromModule"
            args["data"] = to_0x_hex_str(HexBytes(args["data"]))
        elif event_name == "ApproveHash":
            internal_tx_decoded.function_name = "approveHash"
            args["hashToApprove"] = to_0x_hex_str(args.pop("approvedHash"))
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
        elif event_name == "ChangedModuleGuard":
            internal_tx_decoded.function_name = "setModuleGuard"
        elif (
            event_name == "SafeReceived" and not self.eth_zksync_compatible_network
        ):  # Received ether
            # zkSync networks deal with native transfers as ERC20, duplicating them during indexing
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

        safe_relevant_tx: SafeRelevantTransaction | None = None
        if internal_tx and internal_tx.is_ether_transfer:
            # Store Incoming Ether Transfers as relevant transactions for a Safe
            safe_relevant_tx = SafeRelevantTransaction(
                ethereum_tx_id=ethereum_tx_hash,
                safe=safe_address,
                timestamp=internal_tx.timestamp,
            )

        logger.debug(
            "[%s] %s - tx-hash=%s - Processed event",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
        )

        if not internal_tx:
            return []
        return [
            internal_tx,
            internal_tx_decoded,
            child_internal_tx,
            safe_relevant_tx,
        ]

    def _get_safe_creation_events(
        self, decoded_elements: list[EventData]
    ) -> dict[ChecksumAddress, list[EventData]]:
        """
        Get the creation events (SafeSetup and ProxyCreation) from decoded elements and generates a dictionary
        that groups these events by Safe address, so they are processed together.

        :param decoded_elements:
        :return: dictionary with creation events by Safe address
        """
        safe_creation_events: dict[ChecksumAddress, list[EventData]] = {}
        for decoded_element in decoded_elements:
            event_name = decoded_element["event"]
            if event_name == "SafeSetup":
                safe_address = decoded_element["address"]
                safe_creation_events.setdefault(safe_address, []).append(
                    decoded_element
                )
            elif event_name == "ProxyCreation":
                safe_address = decoded_element["args"].get("proxy")
                safe_creation_events.setdefault(safe_address, []).append(
                    decoded_element
                )

        return safe_creation_events

    def _process_safe_creation_events(
        self,
        safe_addresses_with_creation_events: dict[ChecksumAddress, list[EventData]],
    ) -> list[InternalTx]:
        """
        Process creation events (ProxyCreation and SafeSetup). They must be processed together.
        Usual order is:
        - SafeSetup
        - ProxyCreation

        :param safe_addresses_with_creation_events:
        :return: Generated InternalTxs for safe creation
        """
        internal_txs: list[InternalTx] = []
        internal_txs_decoded: list[InternalTxDecoded] = []

        logger.debug("Processing Safe Creation events")

        # Check if they were indexed
        safe_creation_events_addresses = set(safe_addresses_with_creation_events.keys())
        logger.debug(
            "Got %d addresses to index, checking if some are indexed",
            len(safe_creation_events_addresses),
        )
        # Check if SafeSetup event was indexed. ProxyCreation must not come after SafeSetup, so we consider
        # indexed a Safe with a SafeSetup event processed (InternalTxDecoded with `function_name="setup"`).
        indexed_addresses = InternalTxDecoded.objects.filter(
            safe_address__in=safe_creation_events_addresses,
            function_name="setup",
        ).values_list("safe_address", flat=True)
        # Ignoring the already indexed contracts
        addresses_to_index = safe_creation_events_addresses - set(indexed_addresses)
        logger.debug(
            "Got %s addresses to index after the check", len(addresses_to_index)
        )

        logger.debug(
            "InternalTx and InternalTxDecoded objects for creation will be built"
        )
        # Track Safe addresses and their creation tx hashes for SafeContract creation
        created_safe_address_with_tx_hash: dict[ChecksumAddress, bytes] = {}

        for safe_address in addresses_to_index:
            events = safe_addresses_with_creation_events[safe_address]

            # Find events by type (each Safe should have at most one of each)
            setup_event: EventData | None = None
            proxy_creation_event: EventData | None = None
            for event in events:
                if event["event"] == "SafeSetup":
                    setup_event = event
                elif event["event"] == "ProxyCreation":
                    proxy_creation_event = event
                else:
                    logger.error("Unexpected event type: %s", event["event"])

            # Process ProxyCreation - creates the proxy contract
            if proxy_creation_event:
                internal_tx = self._get_internal_tx_from_decoded_element(
                    proxy_creation_event,
                    contract_address=proxy_creation_event["args"].get("proxy"),
                    tx_type=InternalTxType.CREATE.value,
                    call_type=None,
                )
                internal_txs.append(internal_tx)

            # Process SafeSetup - initializes the Safe
            if setup_event:
                if not proxy_creation_event:
                    # SafeSetup without ProxyCreation means proxy was created in a previous block
                    # ProxyCreation is also emitted when ProxyCreationL2 or ChainSpecificProxyCreationL2 are emmited on v1.5.0.
                    logger.debug(
                        "[%s] Proxy was created in previous blocks, deleting the old InternalTx",
                        safe_address,
                    )
                    InternalTx.objects.filter(contract_address=safe_address).delete()
                    logger.debug(
                        "[%s] Proxy was created in previous blocks, old InternalTx deleted",
                        safe_address,
                    )

                # Determine trace_address and singleton based on whether ProxyCreation exists
                if proxy_creation_event:
                    setup_trace_address = f"{proxy_creation_event['logIndex']},0"
                    singleton = proxy_creation_event["args"].get("singleton")
                    # contract_address=None signals this came via event indexer with ProxyCreation
                    contract_address = None
                else:
                    setup_trace_address = str(setup_event["logIndex"])
                    singleton = NULL_ADDRESS
                    contract_address = safe_address

                internal_tx = self._get_internal_tx_from_decoded_element(
                    setup_event,
                    contract_address=contract_address,
                    to=singleton,
                    trace_address=setup_trace_address,
                    call_type=EthereumTxCallType.DELEGATE_CALL.value,
                )

                # Generate InternalDecodedTx for SafeSetup event
                setup_args = dict(setup_event["args"])
                setup_args["payment"] = 0
                setup_args["paymentReceiver"] = NULL_ADDRESS
                setup_args["_threshold"] = setup_args.pop("threshold")
                setup_args["_owners"] = setup_args.pop("owners")
                internal_tx_decoded = InternalTxDecoded(
                    internal_tx=internal_tx,
                    function_name="setup",
                    arguments=setup_args,
                    safe_address=internal_tx._from,  # Denormalized for efficient querying
                )
                internal_txs.append(internal_tx)
                internal_txs_decoded.append(internal_tx_decoded)

                # Track for SafeContract creation
                created_safe_address_with_tx_hash[safe_address] = setup_event[
                    "transactionHash"
                ]

        logger.debug("InternalTx and InternalTxDecoded objects for creation were built")

        stored_internal_txs = InternalTx.objects.store_internal_txs_and_decoded_in_db(
            internal_txs, internal_txs_decoded
        )

        # Create SafeContract entries for newly created Safes
        # This ensures SafeContract exists before non-creation events are filtered
        # (when conditional indexing is enabled)
        if created_safe_address_with_tx_hash:
            logger.debug(
                "Creating %d SafeContract entries for new Safes",
                len(created_safe_address_with_tx_hash),
            )
            SafeContract.objects.bulk_create(
                [
                    SafeContract(address=safe_address, ethereum_tx_id=tx_hash)
                    for safe_address, tx_hash in created_safe_address_with_tx_hash.items()
                ],
                ignore_conflicts=True,  # Safe may already exist from previous indexing
            )

        return stored_internal_txs

    def _prefetch_timestamp_for_blocks(
        self, decoded_elements: list[EventData]
    ) -> dict[bytes, datetime.datetime]:
        """
        Prefetch timestamp for every block hash, so it can be used in future steps of processing without
        querying every block independently.

        :param decoded_elements:
        :return: Dict with `blockHash` and `timestamp`
        """
        logger.debug("Start prefetching timestamp for every block hash")
        # Timestamp is required for storing the elements. Retrieve all of them together
        block_hashes = {
            decoded_element["blockHash"] for decoded_element in decoded_elements
        }
        block_hashes_with_timestamp = {
            HexBytes(block_hash): timestamp
            for block_hash, timestamp in EthereumBlock.objects.filter(
                block_hash__in=block_hashes
            ).values_list("block_hash", "timestamp")
        }
        logger.debug("Ended prefetching timestamp for every block hash")
        return block_hashes_with_timestamp

    def _fetch_txs(self, tx_hashes: list[bytes]) -> list[TxData]:
        """
        Fetch transactions from RPC without receipts.
        Used for conditional indexing to check tx._from before deciding to fetch receipts.

        :param tx_hashes: List of transaction hashes to fetch
        :return: List of transactions
        """
        if not tx_hashes:
            return []

        txs: list[TxData] = []
        for tx_hash, tx in zip(
            tx_hashes,
            self.ethereum_client.get_transactions(tx_hashes),
            strict=False,
        ):
            tx = tx or self.ethereum_client.get_transaction(tx_hash)  # Retry if failed
            if tx:
                txs.append(tx)

        return txs

    def _fetch_receipts_and_store(self, txs: list[TxData]) -> int:
        """
        Fetch receipts for allowed transactions and store them in the database.
        Called after filtering by tx._from to avoid fetching receipts for blocklisted txs.

        :param txs: List of allowed transactions to fetch receipts for and store
        :return: Number of transactions inserted
        """
        if not txs:
            return 0

        tx_hashes = [tx["hash"] for tx in txs]

        # Fetch receipts for allowed transactions
        logger.debug(
            "Conditional indexing: fetching %d receipts for allowed txs",
            len(tx_hashes),
        )

        # Build list of (tx, receipt) pairs, only including successful receipt fetches
        txs_with_receipts: list[tuple[TxData, TxReceipt]] = []
        for tx, tx_receipt in zip(
            txs,
            self.ethereum_client.get_transaction_receipts(tx_hashes),
            strict=False,
        ):
            tx_receipt = tx_receipt or self.ethereum_client.get_transaction_receipt(
                tx["hash"]
            )  # Retry if failed
            if tx_receipt:
                txs_with_receipts.append((tx, tx_receipt))
            else:
                logger.warning(
                    "Conditional indexing: failed to fetch receipt for tx %s",
                    to_0x_hex_str(tx["hash"]),
                )

        if not txs_with_receipts:
            return 0

        # Collect block hashes only from txs with successful receipts
        block_hashes = {to_0x_hex_str(tx["blockHash"]) for tx, _ in txs_with_receipts}

        # Create blocks
        logger.debug("Conditional indexing: inserting %d blocks", len(block_hashes))
        self.index_service.txs_create_or_update_from_block_hashes(block_hashes)

        # Create EthereumTx records
        logger.debug(
            "Conditional indexing: inserting %d transactions", len(txs_with_receipts)
        )
        ethereum_txs_to_insert = [
            EthereumTx.objects.from_tx_dict(tx, receipt)
            for tx, receipt in txs_with_receipts
        ]
        return EthereumTx.objects.bulk_create_from_generator(
            iter(ethereum_txs_to_insert), ignore_conflicts=True
        )

    def _process_decoded_elements(
        self, decoded_elements: list[EventData]
    ) -> list[InternalTx]:
        processed_elements: list[InternalTx] = []

        self.block_hashes_with_timestamp = self._prefetch_timestamp_for_blocks(
            decoded_elements
        )

        # Extract Safe creation events by Safe from decoded_elements list
        safe_addresses_creation_events = self._get_safe_creation_events(
            decoded_elements
        )
        if safe_addresses_creation_events:
            # Process safe creation events
            # Note: When conditional indexing is enabled, events are already filtered
            # by tx._from in process_elements() before reaching this point
            creation_events_processed = self._process_safe_creation_events(
                safe_addresses_creation_events
            )
            processed_elements.extend(creation_events_processed)

        # Filter out creation events (SafeSetup, ProxyCreation)
        # Note: When conditional indexing is enabled, decoded_elements are already
        # filtered by _get_processable_events() in process_elements() to only include
        # events that will be processed (SafeContract existence check already done)
        elements_to_process = [
            element
            for element in decoded_elements
            if element["event"] not in ("SafeSetup", "ProxyCreation")
        ]

        # Store everything together in the database if possible
        logger.debug("InternalTx and InternalTx for non creation events will be built")
        internal_txs_to_insert: list[InternalTx] = []
        internal_txs_decoded_to_insert: list[InternalTxDecoded] = []
        safe_relevant_txs: list[SafeRelevantTransaction] = []
        # Process the rest of Safe events. Store all together
        for decoded_element in elements_to_process:
            elements_to_insert = self._process_decoded_element(decoded_element)
            for element_to_insert in elements_to_insert:
                if isinstance(element_to_insert, InternalTx):
                    internal_txs_to_insert.append(element_to_insert)
                elif isinstance(element_to_insert, InternalTxDecoded):
                    internal_txs_decoded_to_insert.append(element_to_insert)
                elif isinstance(element_to_insert, SafeRelevantTransaction):
                    safe_relevant_txs.append(element_to_insert)
        logger.debug("InternalTx and InternalTx for non creation events were built")

        stored_internal_txs: list[InternalTx] = (
            InternalTx.objects.store_internal_txs_and_decoded_in_db(
                internal_txs_to_insert, internal_txs_decoded_to_insert
            )
        )
        logger.debug("Inserting %d SafeRelevantTransaction", len(safe_relevant_txs))
        SafeRelevantTransaction.objects.bulk_create(
            safe_relevant_txs, ignore_conflicts=True
        )
        logger.debug("Inserted %d SafeRelevantTransaction", len(safe_relevant_txs))

        processed_elements.extend(stored_internal_txs)
        return processed_elements
