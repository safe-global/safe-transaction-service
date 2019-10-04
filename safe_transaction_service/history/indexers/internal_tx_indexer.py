import concurrent
from collections import OrderedDict
from logging import getLogger
from typing import Any, Dict, List, Set

from django.db import transaction

from gnosis.eth import EthereumClient

from ..models import EthereumTx, InternalTx, InternalTxDecoded, SafeMasterCopy
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
        self.cached_ethereum_txs = {}
        self.cached_ethereum_traces = {}

    @property
    def database_field(self):
        return 'tx_block_number'

    @property
    def database_model(self):
        return SafeMasterCopy

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
        tx_hashes = OrderedDict.fromkeys([trace['transactionHash']
                                          for trace in (to_traces + from_traces)]).keys()
        log_fn = logger.info if len(tx_hashes) else logger.debug
        log_fn('Found %d relevant txs with %d internal txs between block-number=%d and block-number=%d. Addresses=%s',
               len(to_traces + from_traces), len(tx_hashes), from_block_number, to_block_number, addresses)

        # TODO Remove from here. Prefetch txs and traces. Multiple batch perform better
        if tx_hashes:
            logger.info('Prefetching txs')
            for ethereum_tx in EthereumTx.objects.create_or_update_from_tx_hashes(tx_hashes):
                self.cached_ethereum_txs[ethereum_tx.tx_hash] = ethereum_tx
            logger.info('End prefetching of txs')

            logger.info('Prefetching traces')
            self.cached_ethereum_traces = dict(zip(tx_hashes, self.ethereum_client.parity.trace_transactions(tx_hashes)))
            logger.info('End prefetching of traces')

        return tx_hashes

    @transaction.atomic
    def process_element(self, tx_hash: str) -> List[InternalTx]:
        """
        Search on Ethereum and store internal txs for provided `tx_hash`
        :param tx_hash:
        :return: List of `InternalTx` already stored in database
        """
        logger.info('Fetching traces for tx-hash=%s', tx_hash)
        # traces = self.ethereum_client.parity.trace_transaction(tx_hash)
        traces = self.cached_ethereum_traces.pop(tx_hash)
        logger.info('Got traces %d for tx-hash=%s', len(traces), tx_hash)
        logger.info('Fetching ethereum tx with tx-hash=%s', tx_hash)
        # ethereum_tx = EthereumTx.objects.create_or_update_from_tx_hash(tx_hash)
        ethereum_tx = self.cached_ethereum_txs.pop(tx_hash)
        logger.info('Got ethereum tx with tx-hash=%s', tx_hash)

        return self._process_traces(traces, ethereum_tx)
        # return [self._process_trace(trace, ethereum_tx) for trace in traces]
        # Use multiprocessing to process traces in parallel
        # with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        #     future_internal_txs = [executor.submit(self._process_trace, trace, ethereum_tx)
        #                            for trace in traces]
        #
        #     return [future.result() for future in concurrent.futures.as_completed(future_internal_txs)]

    def _process_traces(self, traces: List[Dict[str, Any]], ethereum_tx: EthereumTx) -> InternalTx:
        internal_txs = InternalTx.objects.bulk_create([InternalTx.objects.build_from_trace(trace, ethereum_tx)
                                                       for trace in traces],
                                                      ignore_conflicts=True)
        internal_txs_decoded = []
        for internal_tx in internal_txs:
            if internal_tx.can_be_decoded:
                try:
                    function_name, arguments = self.tx_decoder.decode_transaction(bytes(internal_tx.data))
                    internal_txs_decoded.append(InternalTxDecoded(internal_tx=internal_tx,
                                                                  function_name=function_name,
                                                                  arguments=arguments))
                except CannotDecode:
                    pass
        if internal_txs_decoded:
            InternalTxDecoded.objects.bulk_create(internal_txs_decoded, ignore_conflicts=True)
        return internal_txs

    def _process_trace(self, trace: Dict[str, Any], ethereum_tx: EthereumTx) -> InternalTx:
        logger.info('Processing trace')
        internal_tx, created = InternalTx.objects.get_or_create_from_trace(trace, ethereum_tx)

        # Decode internal tx if it's a delegate call (not call) and has data
        # As creation of traces are atomic, we can never have an internal_tx without the decoded internal tx
        if created and internal_tx.can_be_decoded:
            try:
                function_name, arguments = self.tx_decoder.decode_transaction(bytes(internal_tx.data))
                internal_tx_decoded = InternalTxDecoded.objects.create(internal_tx=internal_tx,
                                                                       function_name=function_name,
                                                                       arguments=arguments)
            except CannotDecode:
                pass

        logger.info('Trace processed and created=%s', created)
        return internal_tx
