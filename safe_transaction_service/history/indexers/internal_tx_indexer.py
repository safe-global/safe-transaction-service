from logging import getLogger
from typing import Any, Dict, List, Set

from gnosis.eth import EthereumClient

from ..models import InternalTx, InternalTxDecoded
from .transaction_indexer import TransactionIndexer
from .tx_decoder import CannotDecode, TxDecoder

logger = getLogger(__name__)


class InternalTxIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = InternalTxIndexer(EthereumClient(settings.ETHEREUM_TRACING_NODE_URL),
                                             block_process_limit=settings.INTERNAL_TXS_BLOCK_PROCESS_LIMIT)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class InternalTxIndexer(TransactionIndexer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tx_decoder = TxDecoder()

    @property
    def database_field(self):
        return 'tx_block_number'

    def find_relevant_elements(self, addresses: List[str], from_block_number: int,
                               to_block_number: int) -> Set[str]:
        """
        Search for tx hashes with internal txs (in and out) of a `address`
        :param addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: Tx hashes of txs with internal txs relevant for the `addresses`
        """
        logger.debug('Searching for internal txs from block-number=%d to block-number=%d - Addresses=%s',
                     from_block_number, to_block_number, addresses)

        to_traces = self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                             to_block=to_block_number,
                                                             to_address=addresses)

        from_traces = self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                               to_block=to_block_number,
                                                               from_address=addresses)

        # Log INFO if traces found, DEBUG if not
        log_fn = logger.info if to_traces + from_traces else logger.debug
        log_fn('Found %d relevant txs between block-number=%d and block-number=%d. Addresses=%s',
               len(to_traces + from_traces), from_block_number, to_block_number, addresses)

        return set([trace['transactionHash'] for trace in (to_traces + from_traces)])

    def process_element(self, tx_hash: str) -> List[InternalTx]:
        """
        Search on Ethereum and store internal txs for provided `tx_hash`
        :param tx_hash:
        :return: List of `InternalTx` already stored in database
        """
        return self._process_traces(self.ethereum_client.parity.trace_transaction(tx_hash))

    def _process_trace(self, trace: Dict[str, Any]) -> InternalTx:
        ethereum_tx = self.create_or_update_ethereum_tx(trace['transactionHash'])
        internal_tx, created = InternalTx.objects.get_or_create_from_trace(trace, ethereum_tx)

        # Decode internal tx
        if created and internal_tx.is_call and not internal_tx.decoded_tx:
            try:
                function_name, arguments = self.tx_decoder.decode_transaction(internal_tx.data)
                internal_tx_decoded, _ = InternalTxDecoded.objects.get_or_create(internal_tx=internal_tx,
                                                                                 defaults={
                                                                                     'function_name': function_name,
                                                                                     'arguments': arguments}
                                                                                 )
            except CannotDecode:
                pass

        return internal_tx

    def _process_traces(self, traces: List[Dict[str, Any]]) -> List[InternalTx]:
        return [self._process_trace(trace) for trace in traces]
