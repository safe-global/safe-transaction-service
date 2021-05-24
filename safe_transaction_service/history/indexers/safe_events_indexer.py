from functools import cached_property
from logging import getLogger
from typing import List, Optional

from django.db import IntegrityError, transaction
from django.db.models import F

from eth_abi import decode_abi
from hexbytes import HexBytes
from web3.contract import ContractEvent
from web3.types import EventData

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract as get_safe_V1_2_0_contract

from ..models import (EthereumTxCallType, InternalTx, InternalTxDecoded,
                      InternalTxType, SafeL2MasterCopy)
from .abis.gnosis import gnosis_safe_l2_v1_3_0_abi, proxy_factory_v1_3_0_abi
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class SafeEventsIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = SafeEventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, 'instance'):
            del cls.instance


class SafeEventsIndexer(EventsIndexer):
    """
    Indexes Gnosis Safe L2 events
    """

    IGNORE_ADDRESSES_ON_LOG_FILTER = True

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
        l2_contract = self.ethereum_client.w3.eth.contract(abi=gnosis_safe_l2_v1_3_0_abi)
        proxy_factory_contract = self.ethereum_client.w3.eth.contract(abi=proxy_factory_v1_3_0_abi)
        old_contract = get_safe_V1_2_0_contract(self.ethereum_client.w3)
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
    def database_model(self):
        return SafeL2MasterCopy

    @property
    def database_field(self):
        return 'tx_block_number'

    def _process_decoded_element(self, decoded_element: EventData) -> Optional[InternalTx]:
        safe_address = decoded_element['address']
        event_name = decoded_element['event']
        # As log
        log_index = decoded_element['logIndex']
        trace_address = str(log_index)
        args = dict(decoded_element['args'])

        internal_tx = InternalTx(
            ethereum_tx_id=decoded_element['transactionHash'],
            _from=safe_address,
            gas=50000,
            data=b'',
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
            error=None
        )
        internal_tx_decoded = InternalTxDecoded(
            internal_tx=internal_tx,
            function_name='',
            arguments=args,
        )
        if event_name == 'ProxyCreation':
            # Try to update InternalTx created by SafeSetup (if Safe was created using the ProxyFactory) with
            # the master copy used
            safe_address = args.pop('proxy')
            InternalTx.objects.filter(
                ethereum_tx_id=F('ethereum_tx_id'),
                contract_address=safe_address
            ).update(
                to=args.pop('singleton'),
                contract_address=None,
                trace_address=f'{trace_address},0'
            )
            # Add creation internal tx. _from is the address of the proxy instead of the safe_address
            internal_tx.contract_address = safe_address
            internal_tx.tx_type = InternalTxType.CREATE.value
            internal_tx.call_type = None
            internal_tx_decoded = None
        elif event_name == 'SafeSetup':
            internal_tx_decoded.function_name = 'setup'
            internal_tx.contract_address = safe_address
            args['payment'] = 0
            args['paymentReceiver'] = NULL_ADDRESS
            args['_threshold'] = args.pop('threshold')
            args['_owners'] = args.pop('owners')
        elif event_name == 'SafeMultiSigTransaction':
            internal_tx_decoded.function_name = 'execTransaction'
            args['data'] = HexBytes(args['data']).hex()
            args['signatures'] = HexBytes(args['signatures']).hex()
            args['nonce'], args['sender'], args['threshold'] = decode_abi(
                ['uint256', 'address', 'uint256'],
                internal_tx_decoded.arguments.pop('additionalInfo')
            )
        elif event_name == 'SafeModuleTransaction':
            internal_tx_decoded.function_name = 'execTransactionFromModule'
            args['data'] = HexBytes(args['data']).hex()
        elif event_name == 'ApproveHash':
            internal_tx_decoded.function_name = 'approveHash'
            args['hashToApprove'] = args.pop('approvedHash').hex()
        elif event_name == 'EnabledModule':
            internal_tx_decoded.function_name = 'enableModule'
        elif event_name == 'DisabledModule':
            internal_tx_decoded.function_name = 'disableModule'
        elif event_name == 'AddedOwner':
            internal_tx_decoded.function_name = 'addOwnerWithThreshold'
            args['_threshold'] = None
        elif event_name == 'RemovedOwner':
            internal_tx_decoded.function_name = 'removeOwner'
            args['_threshold'] = None
        elif event_name == 'ChangedThreshold':
            internal_tx_decoded.function_name = 'changeThreshold'
            args['_threshold'] = args.pop('threshold')
        elif event_name == 'ChangedFallbackHandler':
            internal_tx_decoded.function_name = 'setFallbackHandler'
        elif event_name == 'ChangedGuard':
            internal_tx_decoded.function_name = 'setGuard'
        elif event_name == 'SafeReceived':  # Received ether
            internal_tx.call_type = EthereumTxCallType.CALL.value
            internal_tx._from = args['sender']
            internal_tx.to = safe_address
            internal_tx.value = args['value']
            internal_tx_decoded = None
        elif event_name == 'ChangedMasterCopy':
            internal_tx_decoded.function_name = 'changeMasterCopy'
            internal_tx.arguments = {
                '_masterCopy': args.get('singleton') or args.get('masterCopy')
            }
        else:
            # 'SignMsg', 'ExecutionFailure', 'ExecutionSuccess',
            # 'ExecutionFromModuleSuccess', 'ExecutionFromModuleFailure'
            internal_tx_decoded = None

        if internal_tx:
            with transaction.atomic():
                try:
                    internal_tx.save()
                    if internal_tx_decoded:
                        internal_tx_decoded.save()
                except IntegrityError:
                    logger.warning('Problem inserting internal_tx', exc_info=True)

        return internal_tx
