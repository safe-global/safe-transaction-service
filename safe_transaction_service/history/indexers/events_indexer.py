from abc import abstractmethod
from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Optional, OrderedDict, Sequence

from django.conf import settings

from eth_typing import ChecksumAddress
from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes
from web3.contract import ContractEvent
from web3.types import EventData, FilterParams, LogReceipt

from .ethereum_indexer import EthereumIndexer, FindRelevantElementsException

logger = getLogger(__name__)


class EventsIndexer(EthereumIndexer):
    """
    Indexes Ethereum events
    """

    IGNORE_ADDRESSES_ON_LOG_FILTER: bool = False  # If True, don't use addresses to filter logs

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('block_process_limit', settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT)
        kwargs.setdefault('block_process_limit_max', settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT_MAX)
        kwargs.setdefault('blocks_to_reindex_again', 6)   # Reindex last 6 blocks every run of the indexer
        kwargs.setdefault('confirmations', 2)   # Due to reorgs, wait for the last 2 blocks
        kwargs.setdefault('query_chunk_size', settings.ETH_EVENTS_QUERY_CHUNK_SIZE)
        kwargs.setdefault('updated_blocks_behind', settings.ETH_EVENTS_UPDATED_BLOCK_BEHIND
                          )  # For last x blocks, process `query_chunk_size` elements together
        super().__init__(*args, **kwargs)

    @property
    @abstractmethod
    def contract_events(self) -> List[ContractEvent]:
        """
        :return: Web3 ContractEvent to listen to
        """
        pass

    @cached_property
    def events_to_listen(self) -> Dict[bytes, ContractEvent]:
        return {HexBytes(event_abi_to_log_topic(event.abi)).hex(): event for event in self.contract_events}

    def _do_node_query(self, addresses: List[ChecksumAddress],
                       from_block_number: int, to_block_number: int) -> List[LogReceipt]:
        """
        Perform query to the node

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return:
        """
        filter_topics = list(self.events_to_listen.keys())
        parameters: FilterParams = {
            'fromBlock': from_block_number,
            'toBlock': to_block_number,
            'topics': [filter_topics]
        }

        if not self.IGNORE_ADDRESSES_ON_LOG_FILTER:
            parameters['address'] = addresses

        return self.ethereum_client.slow_w3.eth.get_logs(parameters)

    def _find_elements_using_topics(self,
                                    addresses: List[ChecksumAddress],
                                    from_block_number: int, to_block_number: int) -> List[LogReceipt]:
        """
        It will get Safe events using all the Gnosis Safe topics for filtering.

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return: LogReceipt for matching events
        """

        try:
            return self._do_node_query(addresses, from_block_number, to_block_number)
        except IOError as e:
            raise FindRelevantElementsException(f'Request error retrieving events '
                                                f'from-block={from_block_number} to-block={to_block_number}') from e
        except ValueError as e:
            # For example, Polygon returns:
            #   ValueError({'code': -32005, 'message': 'eth_getLogs block range too large, range: 138001, max: 100000'})
            # BSC returns:
            #   ValueError({'code': -32000, 'message': 'exceed maximum block range: 5000'})
            logger.warning('%s: Value error retrieving events from-block=%d to-block=%d : %s',
                           self.__class__.__name__, from_block_number, to_block_number, e)
            raise FindRelevantElementsException(f'Request error retrieving events '
                                                f'from-block={from_block_number} to-block={to_block_number}') from e

    @abstractmethod
    def _process_decoded_element(self, decoded_element: EventData) -> Any:
        pass

    def find_relevant_elements(self, addresses: List[ChecksumAddress],
                               from_block_number: int,
                               to_block_number: int,
                               current_block_number: Optional[int] = None) -> List[LogReceipt]:
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
            '%s: Filtering for events from block-number=%d to block-number=%d for %d addresses: %s',
            self.__class__.__name__, from_block_number, to_block_number, len_addresses, addresses[:10]
        )
        log_receipts = self._find_elements_using_topics(addresses, from_block_number, to_block_number)

        len_events = len(log_receipts)
        logger_fn = logger.info if len_events else logger.debug
        logger_fn(
            '%s: Found %d events from block-number=%d to block-number=%d for %d addresses: %s',
            self.__class__.__name__, len_events, from_block_number, to_block_number, len_addresses, addresses[:10]
        )
        return log_receipts

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> List[Any]:
        """
        Process all events found by `find_relevant_elements`

        :param log_receipts: Events to store in database
        :return: List of `EthereumEvent` already stored in database
        """
        if not log_receipts:
            return []
        decoded_elements: List[EventData] = [
            self.events_to_listen[log_receipt['topics'][0].hex()].processLog(log_receipt)
            for log_receipt in log_receipts
        ]
        tx_hashes = OrderedDict.fromkeys([event['transactionHash'] for event in log_receipts]).keys()
        logger.debug('Prefetching and storing %d ethereum txs', len(tx_hashes))
        ethereum_txs = self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug('End prefetching and storing of ethereum txs')
        logger.debug('Processing %d decoded events', len(decoded_elements))
        processed_elements = []
        for decoded_element in decoded_elements:
            processed_element = self._process_decoded_element(decoded_element)
            if processed_element:
                processed_elements.append(processed_element)
        logger.debug('End processing %d decoded events', len(decoded_elements))
        return processed_elements
