from abc import abstractmethod
from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Optional, OrderedDict, Sequence

from django.conf import settings

import gevent
from eth_typing import ChecksumAddress
from eth_utils import event_abi_to_log_topic
from gevent import pool
from hexbytes import HexBytes
from web3.contract.contract import ContractEvent
from web3.exceptions import LogTopicError
from web3.types import EventData, FilterParams, LogReceipt

from safe_transaction_service.utils.utils import chunks

from .element_already_processed_checker import ElementAlreadyProcessedChecker
from .ethereum_indexer import EthereumIndexer, FindRelevantElementsException

logger = getLogger(__name__)


class EventsIndexer(EthereumIndexer):
    """
    Indexes Ethereum events
    """

    # If True, don't use addresses to filter logs
    # Be careful, some nodes have limitations
    # https://docs.nodereal.io/nodereal/meganode/api-docs/bnb-smart-chain-api/eth_getlogs-bsc
    # https://docs.infura.io/infura/networks/ethereum/json-rpc-methods/eth_getlogs#limitations
    IGNORE_ADDRESSES_ON_LOG_FILTER: bool = False

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "block_process_limit", settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT
        )
        kwargs.setdefault(
            "block_process_limit_max", settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT_MAX
        )
        kwargs.setdefault(
            "blocks_to_reindex_again", settings.ETH_EVENTS_BLOCKS_TO_REINDEX_AGAIN
        )  # Reindex last blocks every run of the indexer
        kwargs.setdefault(
            "query_chunk_size", settings.ETH_EVENTS_QUERY_CHUNK_SIZE
        )  # Number of elements to process together when calling `eth_getLogs`
        kwargs.setdefault(
            "updated_blocks_behind", settings.ETH_EVENTS_UPDATED_BLOCK_BEHIND
        )  # For last x blocks, consider them almost updated and process them first

        # Number of concurrent requests to `getLogs`
        self.get_logs_concurrency = settings.ETH_EVENTS_GET_LOGS_CONCURRENCY
        self.element_already_processed_checker = ElementAlreadyProcessedChecker()

        super().__init__(*args, **kwargs)

    @property
    @abstractmethod
    def contract_events(self) -> List[ContractEvent]:
        """
        :return: List of Web3.py `ContractEvent` to listen to
        """

    @cached_property
    def events_to_listen(self) -> Dict[bytes, List[ContractEvent]]:
        """
        Build a dictionary with a `topic` and a list of ABIs to use for decoding. One single topic can have
        multiple ways of decoding as events with different `indexed` parameters must be decoded
        in a different way

        :return: Dictionary with `topic` as the key and a list of `ContractEvent`
        """
        events_to_listen = {}
        for event in self.contract_events:
            key = HexBytes(event_abi_to_log_topic(event.abi)).hex()
            events_to_listen.setdefault(key, []).append(event)
        return events_to_listen

    def _do_node_query(
        self,
        addresses: List[ChecksumAddress],
        from_block_number: int,
        to_block_number: int,
    ) -> List[LogReceipt]:
        """
        Perform query to the node

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return:
        """
        filter_topics = list(self.events_to_listen.keys())
        parameters: FilterParams = {
            "fromBlock": from_block_number,
            "toBlock": to_block_number,
            "topics": [filter_topics],
        }

        if not self.IGNORE_ADDRESSES_ON_LOG_FILTER:
            # Search logs only for the provided addresses
            if self.query_chunk_size:
                addresses_chunks = chunks(addresses, self.query_chunk_size)
            else:
                addresses_chunks = [addresses]

            multiple_parameters = [
                {**parameters, "address": addresses_chunk}
                for addresses_chunk in addresses_chunks
            ]

            gevent_pool = pool.Pool(self.get_logs_concurrency)
            jobs = [
                gevent_pool.spawn(
                    self.ethereum_client.slow_w3.eth.get_logs, single_parameters
                )
                for single_parameters in multiple_parameters
            ]

            with self.auto_adjust_block_limit(from_block_number, to_block_number):
                # Check how long the first job takes
                gevent.joinall(jobs[:1])

            gevent.joinall(jobs)
            return [log_receipt for job in jobs for log_receipt in job.get()]
        else:
            with self.auto_adjust_block_limit(from_block_number, to_block_number):
                return self.ethereum_client.slow_w3.eth.get_logs(parameters)

    def _find_elements_using_topics(
        self,
        addresses: List[ChecksumAddress],
        from_block_number: int,
        to_block_number: int,
    ) -> List[LogReceipt]:
        """
        It will get Safe events using all the Safe topics for filtering.

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return: LogReceipt for matching events
        """

        try:
            return self._do_node_query(addresses, from_block_number, to_block_number)
        except IOError as e:
            raise FindRelevantElementsException(
                f"Request error retrieving events "
                f"from-block={from_block_number} to-block={to_block_number}"
            ) from e
        except ValueError as e:
            # For example, Polygon returns:
            #   ValueError({'code': -32005, 'message': 'eth_getLogs block range too large, range: 138001, max: 100000'})
            # BSC returns:
            #   ValueError({'code': -32000, 'message': 'exceed maximum block range: 5000'})
            logger.warning(
                "%s: Value error retrieving events from-block=%d to-block=%d : %s",
                self.__class__.__name__,
                from_block_number,
                to_block_number,
                e,
            )
            raise FindRelevantElementsException(
                f"Request error retrieving events "
                f"from-block={from_block_number} to-block={to_block_number}"
            ) from e

    @abstractmethod
    def _process_decoded_element(self, decoded_element: EventData) -> Any:
        pass

    def find_relevant_elements(
        self,
        addresses: List[ChecksumAddress],
        from_block_number: int,
        to_block_number: int,
        current_block_number: Optional[int] = None,
    ) -> List[LogReceipt]:
        """
        Search for log receipts for Safe events

        :param addresses: Not used
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :param current_block_number: Current block number (for cache purposes)
        :return: LogReceipt for matching events
        """
        len_addresses = len(addresses)
        logger.debug(
            "%s: Filtering for events from block-number=%d to block-number=%d for %d addresses",
            self.__class__.__name__,
            from_block_number,
            to_block_number,
            len_addresses,
        )
        log_receipts = self._find_elements_using_topics(
            addresses, from_block_number, to_block_number
        )

        len_log_receipts = len(log_receipts)
        logger_fn = logger.info if len_log_receipts else logger.debug
        logger_fn(
            "%s: Found %d events from block-number=%d to block-number=%d for %d addresses",
            self.__class__.__name__,
            len_log_receipts,
            from_block_number,
            to_block_number,
            len_addresses,
        )
        return log_receipts

    def decode_element(self, log_receipt: LogReceipt) -> Optional[EventData]:
        """
        :param log_receipt:
        :return: Decode `log_receipt` using all the possible ABIs for the topic. Returns `EventData` if successful,
            or `None` if decoding was not possible
        """
        for event_to_listen in self.events_to_listen[log_receipt["topics"][0].hex()]:
            # Try to decode using all the existing ABIs
            # One topic can have multiple matching ABIs due to `indexed` elements changing how to decode it
            try:
                return event_to_listen.process_log(log_receipt)
            except LogTopicError:
                continue

        logger.error(
            "Unexpected log format for log-receipt %s",
            log_receipt,
        )
        return None

    def decode_elements(self, log_receipts: Sequence[LogReceipt]) -> List[EventData]:
        """
        :param log_receipts:
        :return: Decode `log_receipts` and return a list of `EventData`. If a `log_receipt` cannot be decoded
            `EventData` it will be skipped
        """
        decoded_elements = []
        for log_receipt in log_receipts:
            if decoded_element := self.decode_element(log_receipt):
                decoded_elements.append(decoded_element)
        return decoded_elements

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> List[Any]:
        """
        Process all events found by `find_relevant_elements`

        :param log_receipts: Events to store in database
        :return: List of events already stored in database
        """
        if not log_receipts:
            return []

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
        decoded_elements: List[EventData] = self.decode_elements(
            not_processed_log_receipts
        )
        tx_hashes = OrderedDict.fromkeys(
            [event["transactionHash"] for event in not_processed_log_receipts]
        ).keys()
        logger.debug("Prefetching and storing %d ethereum txs", len(tx_hashes))
        self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug("End prefetching and storing of ethereum txs")
        logger.debug("Processing %d decoded events", len(decoded_elements))
        processed_elements = []
        for decoded_element in decoded_elements:
            if processed_element := self._process_decoded_element(decoded_element):
                processed_elements.append(processed_element)
        logger.debug("End processing %d decoded events", len(decoded_elements))

        logger.debug("Marking events as processed")
        for log_receipt in not_processed_log_receipts:
            self.element_already_processed_checker.mark_as_processed(
                log_receipt["transactionHash"],
                log_receipt["blockHash"],
                log_receipt["logIndex"],
            )
        logger.debug("Marked events as processed")

        return processed_elements
