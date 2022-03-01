from functools import cached_property
from logging import getLogger
from typing import List, Optional

from django.db import IntegrityError, transaction

from eth_abi import decode_abi
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.contract import ContractEvent
from web3.types import EventData

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_V1_1_1_contract

from ..models import (
    EthereumBlock,
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    SafeMasterCopy,
)
from .abis.gnosis import gnosis_safe_l2_v1_3_0_abi, proxy_factory_v1_3_0_abi
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class SafeEventsIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = SafeEventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))
        return cls.instance

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
            bytes32 txHash, uint256 payment
        );

        event ExecutionSuccess(
            bytes32 txHash, uint256 payment
        );

        event EnabledModule(address module);
        event DisabledModule(address module);
        event ExecutionFromModuleSuccess(address indexed module);
        event ExecutionFromModuleFailure(address indexed module);

        event AddedOwner(address owner);
        event RemovedOwner(address owner);
        event ChangedThreshold(uint256 threshold);

        event SafeReceived(address indexed sender, uint256 value);  // Incoming ether

        event ChangedFallbackHandler(address handler);
        event ChangedGuard(address guard);

        # ProxyFactory
        event ProxyCreation(GnosisSafeProxy proxy, address singleton);

        :return:
        """
        l2_contract = self.ethereum_client.w3.eth.contract(
            abi=gnosis_safe_l2_v1_3_0_abi
        )
        proxy_factory_contract = self.ethereum_client.w3.eth.contract(
            abi=proxy_factory_v1_3_0_abi
        )
        old_contract = get_safe_V1_1_1_contract(self.ethereum_client.w3)
        return [
            l2_contract.events.SafeMultiSigTransaction(),
            l2_contract.events.SafeModuleTransaction(),
            l2_contract.events.SafeSetup(),
            l2_contract.events.ApproveHash(),
            l2_contract.events.SignMsg(),
            l2_contract.events.ExecutionFailure(),
            l2_contract.events.ExecutionSuccess(),
            # Modules
            l2_contract.events.EnabledModule(),
            l2_contract.events.DisabledModule(),
            l2_contract.events.ExecutionFromModuleSuccess(),
            l2_contract.events.ExecutionFromModuleFailure(),
            # Owners
            l2_contract.events.AddedOwner(),
            l2_contract.events.RemovedOwner(),
            l2_contract.events.ChangedThreshold(),
            # Incoming Ether
            l2_contract.events.SafeReceived(),
            # Changed FallbackHandler
            l2_contract.events.ChangedFallbackHandler(),
            # Changed Guard
            l2_contract.events.ChangedGuard(),
            # Change Master Copy
            old_contract.events.ChangedMasterCopy(),
            # Proxy creation
            proxy_factory_contract.events.ProxyCreation(),
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
        ethereum_tx_hash = decoded_element["transactionHash"]
        ethereum_block = EthereumBlock.objects.values("number", "timestamp").get(
            txs=ethereum_tx_hash
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
        child_internal_tx = None  # For Ether transfers
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
        elif event_name == "SafeMultiSigTransaction":
            internal_tx_decoded.function_name = "execTransaction"
            data = HexBytes(args["data"])
            args["data"] = data.hex()
            args["signatures"] = HexBytes(args["signatures"]).hex()
            args["nonce"], args["sender"], args["threshold"] = decode_abi(
                ["uint256", "address", "uint256"],
                internal_tx_decoded.arguments.pop("additionalInfo"),
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
            internal_tx.arguments = {
                "_masterCopy": args.get("singleton") or args.get("masterCopy")
            }
        else:
            # 'SignMsg', 'ExecutionFailure', 'ExecutionSuccess',
            # 'ExecutionFromModuleSuccess', 'ExecutionFromModuleFailure'
            internal_tx_decoded = None

        if internal_tx:
            with transaction.atomic():
                try:
                    internal_tx.save()
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

        return internal_tx
