from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction

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
        return InternalTxDecoded.objects.filter(
            function_name="setup",
            internal_tx___from=safe_address,
            internal_tx__contract_address=None,
        ).exists()

    @transaction.atomic
    def decode_elements(self, *args) -> List[EventData]:
        return super().decode_elements(*args)

    def _get_internal_tx_from_decoded_event(
        self, decoded_event: EventData, **kwargs
    ) -> InternalTx:
        """
        Creates an InternalTx instance from the given decoded_event.
        Allows overriding object parameters with additional keyword arguments.

        :param decoded_event:
        :param kwargs:
        :return:
        """
        ethereum_tx_hash = HexBytes(decoded_event["transactionHash"])
        ethereum_block_number = decoded_event["blockNumber"]
        ethereum_block_timestamp = EthereumBlock.objects.get_timestamp_by_hash(
            decoded_event["blockHash"]
        )
        address = decoded_event["address"]
        default_trace_address = str(decoded_event["logIndex"])

        # Setting default values
        internal_tx = InternalTx(
            ethereum_tx_id=ethereum_tx_hash,
            timestamp=ethereum_block_timestamp,
            block_number=ethereum_block_number,
            _from=address,
            gas=50000,
            data=b"",
            to=decoded_event["args"].get("to", NULL_ADDRESS),
            value=decoded_event["args"].get("value", 0),
            gas_used=50000,
            contract_address=None,
            code=None,
            output=None,
            refund_address=None,
            tx_type=InternalTxType.CALL.value,
            call_type=EthereumTxCallType.CALL.value,
            trace_address=default_trace_address,
            error=None,
        )
        # Overriding passed keys
        for key, value in kwargs.items():
            if hasattr(internal_tx, key):
                setattr(internal_tx, key, value)
            else:
                raise AttributeError(f"Invalid atribute {key} for InternalTx")

        return internal_tx

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
        ethereum_block_timestamp = EthereumBlock.objects.get_timestamp_by_hash(
            decoded_element["blockHash"]
        )
        logger.debug(
            "[%s] %s - tx-hash=%s - Processing event %s",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
            decoded_element,
        )

        internal_tx = self._get_internal_tx_from_decoded_event(
            decoded_element,
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            to=NULL_ADDRESS,
            value=0,
        )
        child_internal_tx: Optional[InternalTx] = None  # For Ether transfers
        internal_tx_decoded = InternalTxDecoded(
            internal_tx=internal_tx,
            function_name="",
            arguments=args,
        )

        if event_name == "ProxyCreation" or event_name == "SafeSetup":
            # Will ignore these events because were indexed in process_safe_creation_events
            internal_tx = None

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
                child_internal_tx = self._get_internal_tx_from_decoded_event(
                    decoded_element,
                    gas=23000,
                    gas_used=23000,
                    trace_address=f"{trace_address},0",
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

        if internal_tx:
            with transaction.atomic():
                try:
                    internal_tx.save()
                    if internal_tx.is_ether_transfer:
                        # Store Incoming Ether Transfers as relevant transactions for a Safe
                        SafeRelevantTransaction.objects.get_or_create(
                            ethereum_tx_id=ethereum_tx_hash,
                            safe=safe_address,
                            defaults={
                                "timestamp": ethereum_block_timestamp,
                            },
                        )
                    if child_internal_tx:
                        child_internal_tx.save()
                    if internal_tx_decoded:
                        internal_tx_decoded.save()
                except IntegrityError as exc:
                    logger.info(
                        "Ignoring already processed event %s for Safe %s on tx-hash=%s: %s",
                        event_name,
                        safe_address,
                        decoded_element["transactionHash"].hex(),
                        exc,
                    )
                    return None

        logger.debug(
            "[%s] %s - tx-hash=%s - Processed event",
            safe_address,
            event_name,
            ethereum_tx_hash_hex,
        )

        return internal_tx

    def _get_safe_creation_events(
        self, decoded_elements: List[EventData]
    ) -> Dict[ChecksumAddress, List[EventData]]:
        """
        Get the creation events (ProxyCreation and SafeSetup) from decoded elements and generates a dictionary that groups these events by Safe address.

        :param decoded_elements:
        :return:
        """
        safe_creation_events: Dict[ChecksumAddress, List[Dict]] = {}
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
        safe_addresses_with_creation_events: Dict[ChecksumAddress, List[EventData]],
    ) -> List[InternalTx]:
        """
        Process creation events (ProxyCreation and SafeSetup).

        :param safe_addresses_with_creation_events:
        :return:
        """
        internal_txs = []
        internal_decoded_txs = []
        # Check if were indexed
        safe_creation_events_addresses = set(safe_addresses_with_creation_events.keys())
        indexed_addresses = InternalTxDecoded.objects.filter(
            internal_tx___from__in=safe_creation_events_addresses,
            function_name="setup",
            internal_tx__contract_address=None,
        ).values_list("internal_tx___from", flat=True)
        # Ignoring the already indexed contracts
        addresses_to_index = safe_creation_events_addresses - set(indexed_addresses)

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
                        # Proxy was created in previous blocks.
                        proxy_creation_event = None
                        # Safe was created and configure it in the next transaction. Remove it if that's the case
                        InternalTx.objects.filter(
                            contract_address=safe_address
                        ).delete()

                    # Generate InternalTx and internalDecodedTx for SafeSetup event
                    setup_trace_address = (
                        f"{str(proxy_creation_event['logIndex'])},0"
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
                    internal_tx = self._get_internal_tx_from_decoded_event(
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
                    internal_decoded_txs.append(internal_tx_decoded)
                elif event["event"] == "ProxyCreation":
                    proxy_creation_event = event
                    # Generate InternalTx for ProxyCreation
                    internal_tx = self._get_internal_tx_from_decoded_event(
                        proxy_creation_event,
                        contract_address=proxy_creation_event["args"].get("proxy"),
                        tx_type=InternalTxType.CREATE.value,
                        call_type=None,
                    )
                    internal_txs.append(internal_tx)
                else:
                    logger.error(f"Event is not a Safe creation event {event['event']}")

        # Store which internal txs where inserted into database
        stored_internal_txs: List[InternalTx] = []
        with transaction.atomic():
            try:
                InternalTx.objects.bulk_create(internal_txs)
                InternalTxDecoded.objects.bulk_create(internal_decoded_txs)
                stored_internal_txs = internal_txs
            except IntegrityError:
                logger.info(
                    "Cannot bulk create the provided Safe Creation Events, trying one by one"
                )

        if internal_txs and not stored_internal_txs:
            # Fallback handler in case of integrity error
            for internal_decoded_tx in internal_decoded_txs:
                try:
                    with transaction.atomic():
                        # Insert first the internal_tx with internalDecodedTx relation
                        InternalTx.save(internal_decoded_tx.internal_tx)
                        InternalTxDecoded.save(internal_decoded_tx)
                        # Remove inserted internal transactions from the list
                        internal_txs.remove(internal_decoded_tx.internal_tx)
                        stored_internal_txs.append(internal_tx)
                except IntegrityError:
                    logger.info(
                        "Ignoring already processed InternalTx with tx-hash=%s and trace-address=%s",
                        internal_decoded_tx.internal_tx.ethereum_tx_id.hex(),
                        internal_decoded_tx.internal_tx.trace_address,
                    )
                    pass
            # Insert the remaining InternalTxs
            for internal_tx in internal_txs:
                try:
                    with transaction.atomic():
                        InternalTx.save(internal_tx)
                        stored_internal_txs.append(internal_tx)
                except IntegrityError:
                    logger.info(
                        "Ignoring already processed InternalTx with tx-hash=%s and trace-address=%s",
                        internal_tx.ethereum_tx_id.hex(),
                        internal_tx.trace_address,
                    )
                    pass

        return stored_internal_txs

    def _process_decoded_elements(self, decoded_elements: list[EventData]) -> list[Any]:
        processed_elements = []
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

        # Process the rest of Safe events
        for decoded_element in decoded_elements:
            if processed_element := self._process_decoded_element(decoded_element):
                processed_elements.append(processed_element)

        return processed_elements
