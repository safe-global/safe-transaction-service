from collections import OrderedDict
from logging import getLogger
from typing import Dict, Generator, Iterable, List, Optional, Sequence, Set

from django.conf import settings
from django.db import transaction

from eth_typing import HexStr
from hexbytes import HexBytes
from web3.types import BlockTrace, FilterTrace

from gnosis.eth import EthereumClient

from safe_transaction_service.contracts.tx_decoder import (
    CannotDecode,
    UnexpectedProblemDecoding,
    get_safe_tx_decoder,
)
from safe_transaction_service.utils.utils import chunks

from ..models import InternalTx, InternalTxDecoded, MonitoredAddress, SafeMasterCopy
from .element_already_processed_checker import ElementAlreadyProcessedChecker
from .ethereum_indexer import EthereumIndexer, FindRelevantElementsException

logger = getLogger(__name__)


class InternalTxIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls.get_new_instance()
        return cls.instance

    @classmethod
    def get_new_instance(cls) -> "InternalTxIndexer":
        from django.conf import settings

        if settings.ETH_INTERNAL_NO_FILTER:
            instance_class = InternalTxIndexerWithTraceBlock
        else:
            instance_class = InternalTxIndexer

        return instance_class(
            EthereumClient(settings.ETHEREUM_TRACING_NODE_URL),
        )

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class InternalTxIndexer(EthereumIndexer):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "block_process_limit", settings.ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT
        )
        kwargs.setdefault(
            "blocks_to_reindex_again", settings.ETH_INTERNAL_TXS_BLOCKS_TO_REINDEX_AGAIN
        )
        super().__init__(*args, **kwargs)

        self.trace_txs_batch_size: int = settings.ETH_INTERNAL_TRACE_TXS_BATCH_SIZE
        self.number_trace_blocks: int = settings.ETH_INTERNAL_TXS_NUMBER_TRACE_BLOCKS
        self.tx_decoder = get_safe_tx_decoder()
        self.element_already_processed_checker = ElementAlreadyProcessedChecker()

    @property
    def database_field(self):
        return "tx_block_number"

    @property
    def database_queryset(self):
        return SafeMasterCopy.objects.all()

    def find_relevant_elements(
        self,
        addresses: Sequence[str],
        from_block_number: int,
        to_block_number: int,
        current_block_number: Optional[int] = None,
    ) -> OrderedDict[HexBytes, Optional[FilterTrace]]:
        current_block_number = (
            current_block_number or self.ethereum_client.current_block_number
        )
        # Use `trace_block` for last `number_trace_blocks` blocks and `trace_filter` for the others
        trace_block_number = max(current_block_number - self.number_trace_blocks, 0)
        if from_block_number > trace_block_number:  # Just trace_block
            return self._find_relevant_elements_using_trace_block(
                addresses, from_block_number, to_block_number
            )
        elif to_block_number < trace_block_number:  # Just trace_filter
            return self._find_relevant_elements_using_trace_filter(
                addresses, from_block_number, to_block_number
            )
        else:  # trace_filter for old blocks and trace_block for the most recent ones
            logger.debug(
                "Using trace_filter from-block=%d to-block=%d and trace_block from-block=%d to-block=%d",
                from_block_number,
                trace_block_number,
                trace_block_number,
                to_block_number,
            )
            relevant_elements = self._find_relevant_elements_using_trace_filter(
                addresses, from_block_number, trace_block_number
            )
            relevant_elements.update(
                self._find_relevant_elements_using_trace_block(
                    addresses, trace_block_number + 1, to_block_number
                )
            )
            return relevant_elements

    def _find_relevant_elements_using_trace_block(
        self, addresses: Sequence[str], from_block_number: int, to_block_number: int
    ) -> OrderedDict[HexBytes, FilterTrace]:
        addresses_set = set(addresses)  # More optimal to use with `in`
        logger.debug(
            "Using trace_block from-block=%d to-block=%d",
            from_block_number,
            to_block_number,
        )
        try:
            block_numbers = list(range(from_block_number, to_block_number + 1))

            with self.auto_adjust_block_limit(from_block_number, to_block_number):
                blocks_traces: BlockTrace = self.ethereum_client.tracing.trace_blocks(
                    block_numbers
                )
            traces: OrderedDict[HexStr, FilterTrace] = OrderedDict()
            relevant_tx_hashes: Set[HexStr] = set()
            for block_number, block_traces in zip(block_numbers, blocks_traces):
                if not block_traces:
                    logger.warning("Empty `trace_block` for block=%d", block_number)

                for trace in block_traces:
                    transaction_hash = trace.get("transactionHash")
                    if transaction_hash:
                        traces.setdefault(transaction_hash, []).append(trace)
                        # We're only interested in traces related to the provided addresses
                        if (
                            trace.get("action", {}).get("from") in addresses_set
                            or trace.get("action", {}).get("to") in addresses_set
                        ):
                            relevant_tx_hashes.add(transaction_hash)

            # Remove not relevant traces
            for tx_hash in list(traces.keys()):
                if tx_hash not in relevant_tx_hashes:
                    del traces[tx_hash]

            return traces
        except IOError as e:
            raise FindRelevantElementsException(
                "Request error calling `trace_block`"
            ) from e

    def _find_relevant_elements_using_trace_filter(
        self, addresses: Sequence[str], from_block_number: int, to_block_number: int
    ) -> OrderedDict[HexStr, List]:
        """
        Search for tx hashes with internal txs (in and out) of a `address`

        :param addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: Tx hashes of txs with internal txs relevant for the `addresses`
        """
        logger.debug(
            "Using trace_filter from-block=%d to-block=%d",
            from_block_number,
            to_block_number,
        )

        try:
            # We only need to search for traces `to` the provided addresses
            with self.auto_adjust_block_limit(from_block_number, to_block_number):
                to_traces = self.ethereum_client.tracing.trace_filter(
                    from_block=from_block_number,
                    to_block=to_block_number,
                    to_address=addresses,
                )
        except IOError as e:
            raise FindRelevantElementsException(
                "Request error calling `trace_filter`"
            ) from e
        except ValueError as e:
            # For example, Infura returns:
            #   ValueError: {'code': -32005, 'data': {'from': '0x6BBCE1', 'limit': 10000, 'to': '0x7072DB'}, 'message': 'query returned more than 10000 results. Try with this block range [0x6BBCE1, 0x7072DB].'}
            logger.warning(
                "%s: Value error retrieving trace_filter results from-block=%d to-block=%d : %s",
                self.__class__.__name__,
                from_block_number,
                to_block_number,
                e,
            )
            raise FindRelevantElementsException(
                f"Request error retrieving trace_filter results "
                f"from-block={from_block_number} to-block={to_block_number}"
            ) from e

        # Log INFO if traces found, DEBUG if not
        traces: OrderedDict[HexBytes, None] = OrderedDict()
        for trace in to_traces:
            transaction_hash = trace.get("transactionHash")
            if transaction_hash:
                # Leave this empty, as we are missing traces for the transaction and will need to be fetched later
                traces[transaction_hash] = []

        log_fn = logger.info if traces else logger.debug
        log_fn(
            "Found %d relevant txs with internal txs between block-number=%d and block-number=%d. Addresses=%s",
            len(traces),
            from_block_number,
            to_block_number,
            addresses,
        )

        return traces

    def _get_internal_txs_to_decode(
        self, tx_hashes: Sequence[str]
    ) -> Generator[InternalTxDecoded, None, None]:
        """
        Retrieve relevant `InternalTxs` and if possible decode them to return `InternalTxsDecoded`

        :return: A `InternalTxDecoded` generator to be more RAM friendly
        """
        for internal_tx in (
            InternalTx.objects.can_be_decoded()
            .filter(ethereum_tx__in=tx_hashes)
            .iterator()
        ):
            try:
                data = bytes(internal_tx.data)
                function_name, arguments = self.tx_decoder.decode_transaction(data)
                yield InternalTxDecoded(
                    internal_tx=internal_tx,
                    function_name=function_name,
                    arguments=arguments,
                    processed=False,
                )
            except CannotDecode as exc:
                logger.debug("Cannot decode %s: %s", data.hex(), exc)
            except UnexpectedProblemDecoding as exc:
                logger.warning("Unexpected problem decoding %s: %s", data.hex(), exc)

    def trace_transactions(
        self, tx_hashes: Sequence[HexStr], batch_size: int
    ) -> Iterable[List[FilterTrace]]:
        batch_size = batch_size or len(tx_hashes)  # If `0`, don't use batches
        for tx_hash_chunk in chunks(list(tx_hashes), batch_size):
            tx_hash_chunk = list(tx_hash_chunk)
            try:
                yield from self.ethereum_client.tracing.trace_transactions(
                    tx_hash_chunk
                )
            except IOError:
                logger.error(
                    "Problem calling `trace_transactions` with %d txs. "
                    "Try lowering ETH_INTERNAL_TRACE_TXS_BATCH_SIZE",
                    len(tx_hash_chunk),
                    exc_info=True,
                )
                raise

    def process_elements(
        self, tx_hash_with_traces: OrderedDict[HexBytes, Optional[FilterTrace]]
    ) -> List[HexBytes]:
        """
        :param tx_hash_with_traces:
        :return: Inserted `InternalTx` objects
        """
        if not tx_hash_with_traces:
            return []

        # Copy as we might modify it
        tx_hash_with_traces = dict(tx_hash_with_traces)

        logger.debug(
            "Prefetching and storing %d ethereum txs", len(tx_hash_with_traces)
        )

        tx_hashes = []
        tx_hashes_missing_traces = []
        for tx_hash in list(tx_hash_with_traces.keys()):
            # Check if transactions have already been processed
            # Provide block_hash if available as a mean to prevent reorgs
            block_hash = (
                tx_hash_with_traces[tx_hash][0]["blockHash"]
                if tx_hash_with_traces[tx_hash]
                else None
            )
            if not self.element_already_processed_checker.is_processed(
                tx_hash, block_hash
            ):
                tx_hashes.append(tx_hash)
                # Traces can be already populated if using `trace_block`, but with `trace_filter`
                # some traces will be missing and `trace_transaction` needs to be called
                if not tx_hash_with_traces[tx_hash]:
                    tx_hashes_missing_traces.append(tx_hash)
            else:
                # Traces were already processed
                del tx_hash_with_traces[tx_hash]

        ethereum_txs = self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug("End prefetching and storing of ethereum txs")

        logger.debug("Prefetching of traces(internal txs)")
        missing_traces_lists = self.trace_transactions(
            tx_hashes_missing_traces, batch_size=self.trace_txs_batch_size
        )
        for tx_hash_missing_traces, missing_traces in zip(
            tx_hashes_missing_traces, missing_traces_lists
        ):
            tx_hash_with_traces[tx_hash_missing_traces] = missing_traces

        internal_txs = (
            InternalTx.objects.build_from_trace(trace, ethereum_tx)
            for ethereum_tx in ethereum_txs
            for trace in self.ethereum_client.tracing.filter_out_errored_traces(
                tx_hash_with_traces[HexBytes(ethereum_tx.tx_hash)]
            )
        )

        logger.debug("End prefetching of traces(internal txs)")

        with transaction.atomic():
            logger.debug("Storing traces")
            revelant_internal_txs_batch = (
                trace for trace in internal_txs if trace.is_relevant
            )
            traces_stored = InternalTx.objects.bulk_create_from_generator(
                revelant_internal_txs_batch, ignore_conflicts=True
            )
            logger.debug("End storing of %d traces", traces_stored)

            logger.debug("Start decoding and storing of decoded traces")
            #  Pass `tx_hashes` instead of `InternalTxs` to `_get_internal_txs_to_decode`
            #  as they must be retrieved again.
            #  `bulk_create` with `ignore_conflicts=True` do not populate the `pk` when storing objects
            internal_txs_decoded = InternalTxDecoded.objects.bulk_create_from_generator(
                self._get_internal_txs_to_decode(tx_hashes), ignore_conflicts=True
            )
            logger.debug(
                "End decoding and storing of %d decoded traces", internal_txs_decoded
            )

        # Mark traces as processed
        for tx_hash in list(tx_hash_with_traces.keys()):
            block_hash = (
                tx_hash_with_traces[tx_hash][0]["blockHash"]
                if tx_hash_with_traces[tx_hash]
                else None
            )
            self.element_already_processed_checker.mark_as_processed(
                tx_hash, block_hash
            )
        return tx_hashes


class InternalTxIndexerWithTraceBlock(InternalTxIndexer):
    """
    Indexer for nodes not supporting `trace_filter`, so it will always use `trace_block`
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_almost_updated_addresses(
        self, current_block_number: int
    ) -> List[MonitoredAddress]:
        """
        Return every address. As we are using `trace_block` every master copy should be processed together

        :param current_block_number:
        :return:
        """
        return self.get_not_updated_addresses(current_block_number)

    def find_relevant_elements(
        self,
        addresses: Sequence[str],
        from_block_number: int,
        to_block_number: int,
        current_block_number: Optional[int] = None,
    ) -> Dict[HexStr, FilterTrace]:
        return self._find_relevant_elements_using_trace_block(
            addresses, from_block_number, to_block_number
        )
