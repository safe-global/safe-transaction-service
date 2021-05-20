from abc import abstractmethod
from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Optional, OrderedDict, Sequence

from eth_typing import ChecksumAddress
from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes
from web3.contract import ContractEvent
from web3.types import EventData, FilterParams, LogReceipt

from .ethereum_indexer import EthereumIndexer

logger = getLogger(__name__)


class EventsIndexer(EthereumIndexer):
    """
    Indexes Ethereum events
    """

    IGNORE_ADDRESSES_ON_LOG_FILTER: Optional[bool] = None  # Don't use addresses to filter logs

    def __init__(self, *args, **kwargs):
        kwargs['first_block_threshold'] = 0
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
        logger.debug('Filtering for Safe events from block-number=%d to block-number=%d', from_block_number,
                     to_block_number)
        log_receipts = self._find_elements_using_topics(addresses, from_block_number, to_block_number)

        len_events = len(log_receipts)
        logger_fn = logger.info if len_events else logger.debug
        logger_fn('Found %d Safe events between block-number=%d and block-number=%d',
                  len_events, from_block_number, to_block_number)
        return log_receipts

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
        filter_topics = list(self.events_to_listen.keys())
        parameters: FilterParams = {
            'fromBlock': from_block_number,
            'toBlock': to_block_number,
            'topics': [filter_topics]
        }

        if not self.IGNORE_ADDRESSES_ON_LOG_FILTER:
            parameters['address'] = addresses

        try:
            return self.ethereum_client.slow_w3.eth.get_logs(parameters)
        except IOError as e:
            raise self.FindRelevantElementsException('Request error retrieving Safe L2 events') from e

    @abstractmethod
    def _process_decoded_element(self, decoded_element: EventData) -> Any:
        pass

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> List[Any]:
        """
        Process all events found by `find_relevant_elements`
        :param log_receipts: Events to store in database
        :return: List of `EthereumEvent` already stored in database
        """
        decoded_elements: List[EventData] = [
            self.events_to_listen[log_receipt['topics'][0].hex()].processLog(log_receipt)
            for log_receipt in log_receipts
        ]
        tx_hashes = OrderedDict.fromkeys([event['transactionHash'] for event in log_receipts]).keys()
        logger.debug('Prefetching and storing %d ethereum txs', len(tx_hashes))
        ethereum_txs = self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug('End prefetching and storing of ethereum txs')
        logger.debug('Processing %d Safe decoded events', len(decoded_elements))
        processed_elements = [self._process_decoded_element(decoded_element) for decoded_element in decoded_elements]
        logger.debug('End processing Safe decoded events', len(decoded_elements))
        return processed_elements
