import datetime
from functools import cached_property
from logging import getLogger
from typing import Any

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
)
from safe_eth.util.util import to_0x_hex_str
from web3.contract.contract import ContractEvent
from web3.types import EventData

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
        kwargs.setdefault(
            "eth_zksync_compatible_network", settings.ETH_ZKSYNC_COMPATIBLE_NETWORK
        )
        self.eth_zksync_compatible_network = kwargs["eth_zksync_compatible_network"]
        # Cache timestamp for block hashes
        self.block_hashes_with_timestamp: dict[bytes, datetime.datetime] = {}
        super().__init__(*args, **kwargs)

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
        Get the creation events (ProxyCreation and SafeSetup) from decoded elements and generates a dictionary
        that groups these events by Safe address, so they are processed together

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
        Process creation events (ProxyCreation and SafeSetup). They must be processed together

        :param safe_addresses_with_creation_events:
        :return:
        """
        internal_txs = []
        internal_txs_decoded = []

        logger.debug("Processing Safe Creation events")

        # Check if they were indexed
        safe_creation_events_addresses = set(safe_addresses_with_creation_events.keys())
        logger.debug(
            "Got %d addresses to index, checking if some are indexed",
            len(safe_creation_events_addresses),
        )
        indexed_addresses = InternalTxDecoded.objects.filter(
            internal_tx___from__in=safe_creation_events_addresses,
            function_name="setup",
            internal_tx__contract_address=None,
        ).values_list("internal_tx___from", flat=True)
        # Ignoring the already indexed contracts
        addresses_to_index = safe_creation_events_addresses - set(indexed_addresses)
        logger.debug(
            "Got %s addresses to index after the check", len(addresses_to_index)
        )

        logger.debug(
            "InternalTx and InternalTxDecoded objects for creation will be built"
        )
        for safe_address in addresses_to_index:
            events = safe_addresses_with_creation_events[safe_address]
            for event_position, event in enumerate(events):
                if event["event"] == "SafeSetup":
                    setup_event = event
                    # If we have both events we should extract Singleton and trace_address from ProxyCreation event
                    if len(events) > 1:
                        if (
                            event_position == 0
                            and events[1]["event"] == "ProxyCreation"
                        ):
                            # Usually SafeSetup is the first event and next is ProxyCreation when ProxyFactory is called with initializer.
                            proxy_creation_event = events[1]
                        elif (
                            event_position == 1
                            and events[0]["event"] == "ProxyCreation"
                        ):
                            # ProxyCreation first and SafeSetup later
                            proxy_creation_event = events[0]
                        else:
                            # This shouldn't happen, as there will be no proxy_creation event
                            continue
                    else:
                        logger.debug(
                            "[%s] Proxy was created in previous blocks, deleting the old InternalTx",
                            safe_address,
                        )
                        # Proxy was created in previous blocks.
                        proxy_creation_event = None
                        # Safe was created and configure it in the next transaction. Remove it if that's the case
                        InternalTx.objects.filter(
                            contract_address=safe_address
                        ).delete()
                        logger.debug(
                            "[%s] Proxy was created in previous blocks, old InternalTx deleted",
                            safe_address,
                        )

                    # Generate InternalTx and internalDecodedTx for SafeSetup event
                    setup_trace_address = (
                        f"{proxy_creation_event['logIndex']},0"
                        if proxy_creation_event
                        else str(setup_event["logIndex"])
                    )
                    singleton = (
                        proxy_creation_event["args"].get("singleton")
                        if proxy_creation_event
                        else NULL_ADDRESS
                    )
                    # Keep previous implementation
                    contract_address = None if proxy_creation_event else safe_address
                    internal_tx = self._get_internal_tx_from_decoded_element(
                        setup_event,
                        contract_address=contract_address,
                        to=singleton,
                        trace_address=setup_trace_address,
                        call_type=EthereumTxCallType.DELEGATE_CALL.value,
                    )
                    # Generate InternalDecodedTx for SafeSetup event
                    setup_args = dict(event["args"])
                    setup_args["payment"] = 0
                    setup_args["paymentReceiver"] = NULL_ADDRESS
                    setup_args["_threshold"] = setup_args.pop("threshold")
                    setup_args["_owners"] = setup_args.pop("owners")
                    internal_tx_decoded = InternalTxDecoded(
                        internal_tx=internal_tx,
                        function_name="setup",
                        arguments=setup_args,
                    )
                    internal_txs.append(internal_tx)
                    internal_txs_decoded.append(internal_tx_decoded)
                elif event["event"] == "ProxyCreation":
                    proxy_creation_event = event
                    # Generate InternalTx for ProxyCreation
                    internal_tx = self._get_internal_tx_from_decoded_element(
                        proxy_creation_event,
                        contract_address=proxy_creation_event["args"].get("proxy"),
                        tx_type=InternalTxType.CREATE.value,
                        call_type=None,
                    )
                    internal_txs.append(internal_tx)
                else:
                    logger.error(f"Event is not a Safe creation event {event['event']}")

        logger.debug("InternalTx and InternalTxDecoded objects for creation were built")
        return InternalTx.objects.store_internal_txs_and_decoded_in_db(
            internal_txs, internal_txs_decoded
        )

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

    def _process_decoded_elements(self, decoded_elements: list[EventData]) -> list[Any]:
        processed_elements = []

        self.block_hashes_with_timestamp = self._prefetch_timestamp_for_blocks(
            decoded_elements
        )

        # Extract Safe creation events by Safe from decoded_elements list
        safe_addresses_creation_events = self._get_safe_creation_events(
            decoded_elements
        )
        if safe_addresses_creation_events:
            # Process safe creation events
            creation_events_processed = self._process_safe_creation_events(
                safe_addresses_creation_events
            )
            processed_elements.extend(creation_events_processed)

        # Store everything together in the database if possible
        logger.debug("InternalTx and InternalTx for non creation events will be built")
        internal_txs_to_insert: list[InternalTx] = []
        internal_txs_decoded_to_insert: list[InternalTxDecoded] = []
        safe_relevant_txs: list[SafeRelevantTransaction] = []
        # Process the rest of Safe events. Store all together
        for decoded_element in decoded_elements:
            elements_to_insert = self._process_decoded_element(decoded_element)
            for element_to_insert in elements_to_insert:
                if isinstance(element_to_insert, InternalTx):
                    internal_txs_to_insert.append(element_to_insert)
                elif isinstance(element_to_insert, InternalTxDecoded):
                    internal_txs_decoded_to_insert.append(element_to_insert)
                elif isinstance(element_to_insert, SafeRelevantTransaction):
                    safe_relevant_txs.append(element_to_insert)
        logger.debug("InternalTx and InternalTx for non creation events were built")

        stored_internal_txs = InternalTx.objects.store_internal_txs_and_decoded_in_db(
            internal_txs_to_insert, internal_txs_decoded_to_insert
        )
        logger.debug("Inserting %d SafeRelevantTransaction", len(safe_relevant_txs))
        SafeRelevantTransaction.objects.bulk_create(
            safe_relevant_txs, ignore_conflicts=True
        )
        logger.debug("Inserted SafeRelevantTransaction")

        processed_elements.extend(stored_internal_txs)
        return processed_elements
