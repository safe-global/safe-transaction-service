import time
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any, List, Optional, Sequence, Tuple

from django.db.models import Min

from billiard.exceptions import SoftTimeLimitExceeded
from web3 import Web3

from gnosis.eth import EthereumClient

from ..models import MonitoredAddress
from ..services import IndexService, IndexServiceProvider
from ..utils import chunks

logger = getLogger(__name__)


class EthereumIndexer(ABC):
    """
    This service allows indexing of Ethereum blockchain.
    `database_field` should be defined with the field used to store the current block number for a monitored address
    `find_relevant_elements` elements should be defined with the query to get the relevant txs/events/etc.
    `process_elements` defines what happens with elements found
    So the flow would be `start()` -> `process_addresses` -> `find_revelant_elements` -> `process_elements` ->
    `process_element`
    """
    def __init__(self, ethereum_client: EthereumClient, confirmations: int = 1,
                 block_process_limit: int = 1000, updated_blocks_behind: int = 20,
                 query_chunk_size: int = 100, first_block_threshold: int = 150000,
                 block_auto_process_limit: bool = True):
        """
        :param ethereum_client:
        :param confirmations: Threshold of blocks to scan to prevent reorgs
        :param block_process_limit: Number of blocks to scan at a time for relevant data. `0` == `No limit`
        :param updated_blocks_behind: Number of blocks scanned for an address that can be behind and
        still be considered as almost updated. For example, if `updated_blocks_behind` is 100,
        `current block number` is 200, and last scan for an address was stopped on block 150, address
        is almost updated (200 - 100 < 150)
        :param query_chunk_size: Number of addresses to query for relevant data in the same request. By testing,
        it seems that `200` can be a good value
        :param first_block_threshold: First block to start scanning for address. For example, maybe a contract
        we are listening to was created in block 2000, but there's a tx sending funds to it in block 1500
        :param block_auto_process_limit: Auto increase or decrease the `block_process_limit`
        based on congestion algorithm
        """
        self.ethereum_client = ethereum_client
        self.index_service: IndexService = IndexServiceProvider()
        self.index_service.ethereum_client = self.ethereum_client  # Use tracing ethereum client
        self.confirmations = confirmations
        self.initial_block_process_limit = block_process_limit
        self.block_process_limit = block_process_limit
        self.updated_blocks_behind = updated_blocks_behind
        self.query_chunk_size = query_chunk_size
        self.first_block_threshold = first_block_threshold
        self.block_auto_process_limit = block_auto_process_limit

    class FindRelevantElementsException(Exception):
        pass

    @property
    @abstractmethod
    def database_field(self):
        """
        Database field on `database_model` to store scan status
        :return:
        """
        pass

    @property
    def database_model(self):
        return MonitoredAddress

    @abstractmethod
    def find_relevant_elements(self, addresses: Sequence[str], from_block_number: int,
                               to_block_number: int,
                               current_block_number: Optional[int] = None) -> Sequence[Any]:
        """
        Find blockchain relevant elements for the `addresses`
        :param addresses:
        :param from_block_number
        :param to_block_number
        :param current_block_number:
        :return: Set of relevant elements
        """
        pass

    def process_element(self, element: Any) -> List[Any]:
        """
        Process provided `element` to retrieve relevant data (internal txs, events...)
        :param element:
        :return:
        """
        raise NotImplementedError

    def process_elements(self, elements: Sequence[Any]) -> Sequence[Any]:
        processed_objects = []
        for i, element in enumerate(elements):
            logger.info('Processing element %d/%d', i + 1, len(list(elements)))
            processed_objects.append(self.process_element(element))
        # processed_objects = [self.process_element(element) for element in elements]
        return [item for sublist in processed_objects for item in sublist]

    def get_almost_updated_addresses(self, current_block_number: int) -> List[MonitoredAddress]:
        """
        For addresses almost updated (< `updated_blocks_behind` blocks) we process them together
        (`query_chunk_size` addresses at the same time)
        :param current_block_number:
        :return:
        """
        return self.database_model.objects.almost_updated(self.database_field, current_block_number,
                                                          self.updated_blocks_behind, self.confirmations)

    def get_not_updated_addresses(self, current_block_number: int) -> List[MonitoredAddress]:
        """
        For addresses not updated (> `updated_blocks_behind` blocks) we process them one by one (node hangs)
        :param current_block_number:
        :return:
        """
        return self.database_model.objects.not_updated(self.database_field, current_block_number, self.confirmations)

    def update_monitored_address(self, addresses: Sequence[str], from_block_number: int, to_block_number: int) -> int:
        """
        :param addresses: Addresses to have the block number updated
        :param from_block_number: Make sure that no reorg has happened checking that block number was not rollbacked
        :param to_block_number: Block number to be updated
        :return: Number of addresses updated
        """
        updated_addresses = self.database_model.objects.update_addresses(addresses, from_block_number, to_block_number,
                                                                         self.database_field)
        if updated_addresses != len(addresses):
            logger.warning('Possible reorg - Cannot update all indexed addresses=%s '
                           'from-block-number=%d to-block-number=%d',
                           addresses, from_block_number, to_block_number)

        return updated_addresses

    def get_block_numbers_for_search(self, addresses: Sequence[str],
                                     current_block_number: Optional[int] = None) -> Optional[Sequence[Tuple[int, int]]]:
        """
        :param addresses:
        :param current_block_number: To prevent fetching it again
        :return: Minimum common `from_block_number` and `to_block_number` for search of relevant `tx hashes`
        """
        block_process_limit = self.block_process_limit
        confirmations = self.confirmations
        current_block_number = current_block_number or self.ethereum_client.current_block_number

        monitored_contract_queryset = self.database_model.objects.filter(address__in=addresses)
        common_minimum_block_number = monitored_contract_queryset.aggregate(**{
            self.database_field: Min(self.database_field)
        })[self.database_field]

        if common_minimum_block_number is None:  # Empty queryset
            return

        from_block_number = common_minimum_block_number + 1
        if (current_block_number - common_minimum_block_number) <= confirmations:
            return  # We don't want problems with reorgs

        if block_process_limit:
            to_block_number = min(common_minimum_block_number + block_process_limit + 1,
                                  current_block_number - confirmations)
        else:
            to_block_number = current_block_number - confirmations

        return from_block_number, to_block_number

    def process_addresses(self, addresses: Sequence[str],
                          current_block_number: Optional[int] = None) -> Tuple[Sequence[Any], bool]:
        """
        Find and process relevant data for `addresses`, then store and return it
        :param addresses: Addresses to process
        :param current_block_number: To prevent fetching it again
        :return: List of processed data and a boolean (`True` if no more blocks to scan, `False` otherwise)
        """
        assert addresses, 'Addresses cannot be empty!'
        assert all([Web3.isChecksumAddress(address) for address in addresses]), \
            f'An address has invalid checksum: {addresses}'

        current_block_number = current_block_number or self.ethereum_client.current_block_number
        parameters = self.get_block_numbers_for_search(addresses, current_block_number)
        if parameters is None:
            return [], True
        from_block_number, to_block_number = parameters

        updated = to_block_number == (current_block_number - self.confirmations)

        # Optimize number of elements processed every time (block process limit)
        # Check that we are processing the `block_process_limit`, if not, measures are not valid
        if self.block_auto_process_limit and (to_block_number - from_block_number) == self.block_process_limit:
            start = time.time()
        else:
            start = None

        try:
            elements = self.find_relevant_elements(addresses, from_block_number, to_block_number,
                                                   current_block_number=current_block_number)
        except (self.FindRelevantElementsException, SoftTimeLimitExceeded) as e:
            self.block_process_limit = min(self.initial_block_process_limit, 10)  # Set back to less than default
            logger.info('%s: block_process_limit set back to %d', self.__class__.__name__, self.block_process_limit)
            raise e

        if start:
            end = time.time()
            time_diff = end - start
            if time_diff > 30:
                self.block_process_limit //= 2
                logger.info('%s: block_process_limit halved to %d', self.__class__.__name__,
                            self.block_process_limit)
            if time_diff > 10:
                new_block_process_limit = max(self.block_process_limit - 5000, 500)
                self.block_process_limit = new_block_process_limit
                logger.info('%s: block_process_limit decreased to %d', self.__class__.__name__,
                            self.block_process_limit)
            elif time_diff < 1:
                self.block_process_limit *= 2
                logger.info('%s: block_process_limit duplicated to %d', self.__class__.__name__,
                            self.block_process_limit)
            elif time_diff < 3:
                self.block_process_limit += 5000
                logger.info('%s: block_process_limit increased to %d', self.__class__.__name__,
                            self.block_process_limit)

        processed_elements = self.process_elements(elements)

        self.update_monitored_address(addresses, from_block_number, to_block_number)
        return processed_elements, updated

    def start(self) -> int:
        """
        Find and process relevant data for existing database addresses
        :return: Number of elements processed
        """
        current_block_number = self.ethereum_client.current_block_number
        number_processed_elements = 0

        # We need to cast the `iterable` to `list`, if not chunks will not work well when models are updated
        almost_updated_monitored_addresses = list(self.get_almost_updated_addresses(current_block_number))
        almost_updated_monitored_addresses_chunks = chunks(almost_updated_monitored_addresses, self.query_chunk_size)
        for almost_updated_addresses_chunk in almost_updated_monitored_addresses_chunks:
            almost_updated_addresses = [monitored_contract.address
                                        for monitored_contract in almost_updated_addresses_chunk]
            processed_elements, _ = self.process_addresses(almost_updated_addresses, current_block_number)
            number_processed_elements += len(processed_elements)

        for monitored_contract in self.get_not_updated_addresses(current_block_number):
            updated = False
            while not updated:
                processed_elements, updated = self.process_addresses([monitored_contract.address], current_block_number)
                number_processed_elements += len(processed_elements)
        return number_processed_elements
