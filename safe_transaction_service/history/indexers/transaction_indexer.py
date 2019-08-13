from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any, Collection, List, Optional, Tuple

from django.db.models import Min
from web3 import Web3

from gnosis.eth import EthereumClient

from ..models import EthereumBlock, EthereumTx, MonitoredAddress
from ..utils import chunks

logger = getLogger(__name__)


class TransactionIndexer(ABC):
    """
    This service allows indexing of Ethereum blockchain.
    `database_field` should be defined with the field used to store the current block number for a monitored address
    `find_relevant_elements` elements should be defined with the query to get the relevant txs/events/etc.
    `process_element` defines what happens with elements found
    So the flow would be `process_all()` -> `process_addresses` -> `find_revelant_elements` -> `process_element`
    """
    def __init__(self, ethereum_client: EthereumClient, confirmations: int = 6,
                 block_process_limit: int = 10000, updated_blocks_behind: int = 100,
                 query_chunk_size: int = 100, first_block_threshold: int = 150000):
        """
        :param ethereum_client:
        :param confirmations: Threshold of blocks to scan to prevent reorgs
        :param block_process_limit: Number of blocks to scan at a time for relevant data. `0` == `No limit`
        :param updated_blocks_behind: Number of blocks scanned for an address that can be behind and
        still be considered as almost updated. For example, if `updated_blocks_behind` is 100,
        `current block number` is 200, and last scan for an address was stopped on block 150, address
        is almost updated (200 - 100 < 150)
        :param query_chunk_size: Number of addresses to query for relevant data in the same request. By testing,
        it seems that `100` can be a good value
        :param first_block_threshold: First block to start scanning for address. For example, maybe a contract
        we are listening to was created in block 2000, but there's a tx sending funds to it in block 1500
        """
        self.ethereum_client = ethereum_client
        self.confirmations = confirmations
        self.block_process_limit = block_process_limit
        self.updated_blocks_behind = updated_blocks_behind
        self.query_chunk_size = query_chunk_size
        self.first_block_threshold = first_block_threshold

    @property
    @abstractmethod
    def database_field(self):
        """
        Database field on `MonitoredAddress` to store scan status
        :return:
        """
        pass

    @abstractmethod
    def find_relevant_elements(self, addresses: List[str], from_block_number: int,
                               to_block_number: int) -> Collection[Any]:
        """
        Find blockchain relevant elements for the `addresses`
        :param addresses:
        :param from_block_number
        :param to_block_number
        :return: Set of relevant elements
        """
        pass

    @abstractmethod
    def process_element(self, element: Any) -> List[Any]:
        """
        Process provided `element` to retrieve relevant data (internal txs, events...)
        :param element:
        :return:
        """
        pass

    def create_or_update_ethereum_tx(self, tx_hash: str) -> EthereumTx:
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            # For txs stored before being mined
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_tx.block = self.get_or_create_ethereum_block(tx_receipt.blockNumber)
                ethereum_tx.gas_used = tx_receipt.gasUsed
                ethereum_tx.status = tx_receipt.status
                ethereum_tx.transaction_index = tx_receipt.transactionIndex
                ethereum_tx.save(update_fields=['block', 'gas_used', 'status', 'transaction_index'])
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = self.get_or_create_ethereum_block(tx_receipt.blockNumber)
            tx = self.ethereum_client.get_transaction(tx_hash)
            return EthereumTx.objects.create_from_tx(tx, tx_hash, tx_receipt, ethereum_block)

    def get_or_create_ethereum_block(self, block_number: int):
        try:
            return EthereumBlock.objects.get(number=block_number)
        except EthereumBlock.DoesNotExist:
            block = self.ethereum_client.get_block(block_number)
            return EthereumBlock.objects.create_from_block(block)

    def get_almost_updated_addresses(self, current_block_number: int) -> List[MonitoredAddress]:
        """
        For addresses almost updated (< `updated_blocks_behind` blocks) we process them together
        (`query_chunk_size` addresses at the same time)
        :param current_block_number:
        :return:
        """
        return MonitoredAddress.objects.almost_updated(current_block_number, self.database_field,
                                                       self.updated_blocks_behind, self.confirmations)

    def get_not_updated_addresses(self, current_block_number: int) -> List[MonitoredAddress]:
        """
        For addresses not updated (> `updated_blocks_behind` blocks) we process them one by one (node hangs)
        :param current_block_number:
        :return:
        """
        return MonitoredAddress.objects.not_updated(current_block_number, self.database_field, self.confirmations)

    def update_monitored_contract(self, addresses: List[str], to_block_number: int) -> int:
        return MonitoredAddress.objects.update_addresses(addresses, to_block_number, self.database_field)

    def get_block_numbers_for_search(self, addresses: List[str]) -> Optional[Tuple[int, int]]:
        """
        :param addresses:
        :return: Minimum common `from_block_number` and `to_block_number` for search of relevant `tx hashes`
        """
        block_process_limit = self.block_process_limit
        confirmations = self.confirmations
        current_block_number = self.ethereum_client.current_block_number

        monitored_contract_queryset = MonitoredAddress.objects.filter(address__in=addresses)
        common_minimum_block_number = monitored_contract_queryset.aggregate(**{
            self.database_field: Min(self.database_field)
        })[self.database_field]
        if common_minimum_block_number is None:  # Empty queryset
            return

        from_block_number = common_minimum_block_number + 1
        if (current_block_number - common_minimum_block_number) < confirmations:
            return  # We don't want problems with reorgs

        if block_process_limit:
            to_block_number = min(common_minimum_block_number + block_process_limit,
                                  current_block_number - confirmations)
        else:
            to_block_number = current_block_number - confirmations

        return from_block_number, to_block_number

    def process_addresses(self, addresses: List[str]) -> Tuple[List[Any], bool]:
        """
        Find and process relevant data for `addresses`, then store and return it
        :param addresses: Addresses to process
        :return: List of processed data and a boolean (`True` if no more blocks to scan, `False` otherwise)
        """
        assert addresses, 'Addresses cannot be empty!'
        assert all([Web3.isChecksumAddress(address) for address in addresses]), \
            f'An address has invalid checksum: {addresses}'

        parameters = self.get_block_numbers_for_search(addresses)
        if parameters is None:
            return [], True
        from_block_number, to_block_number = parameters
        updated = to_block_number == (self.ethereum_client.current_block_number - self.confirmations)
        elements = self.find_relevant_elements(addresses, from_block_number, to_block_number)
        processed_objects = [self.process_element(element) for element in elements]
        flatten_processed_objects = [item for sublist in processed_objects for item in sublist]

        self.update_monitored_contract(addresses, to_block_number)
        return flatten_processed_objects, updated

    def process_all(self):
        """
        Find and process relevant data for existing addresses
        :return: Number of addresses processed
        """
        current_block_number = self.ethereum_client.current_block_number
        processed_addresses = 0

        # We need to cast the `iterable` to `list`, if not chunks will not work well when models are updated
        almost_updated_monitored_addresses = list(self.get_almost_updated_addresses(current_block_number))
        almost_updated_monitored_addresses_chunks = chunks(almost_updated_monitored_addresses, self.query_chunk_size)
        for almost_updated_addresses_chunk in almost_updated_monitored_addresses_chunks:
            almost_updated_addresses = [monitored_contract.address
                                        for monitored_contract in almost_updated_addresses_chunk]
            self.process_addresses(almost_updated_addresses)
            processed_addresses += len(almost_updated_addresses)

        for monitored_contract in self.get_not_updated_addresses(current_block_number):
            updated = False
            while not updated:
                _, updated = self.process_addresses([monitored_contract.address])
            processed_addresses += 1
        return processed_addresses
