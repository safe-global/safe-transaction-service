import datetime
from collections import OrderedDict
from logging import getLogger
from typing import Iterator, List, NamedTuple, Optional, Sequence

from django.db.models import QuerySet
from django.db.models.query import EmptyQuerySet

from eth_typing import ChecksumAddress
from safe_eth.eth import EthereumClient
from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt

from ...utils.utils import FixedSizeDict
from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    IndexingStatus,
    SafeContract,
    SafeRelevantTransaction,
    TokenTransfer,
)
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class AddressesCache(NamedTuple):
    addresses: set[ChecksumAddress]
    last_checked: Optional[datetime.datetime]


class Erc20EventsIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls.get_new_instance()
        return cls.instance

    @classmethod
    def get_new_instance(cls) -> "Erc20EventsIndexer":
        from django.conf import settings

        return Erc20EventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class Erc20EventsIndexer(EventsIndexer):
    """
    Indexes `ERC20` and `ERC721` `Transfer` events.

    ERC20 Transfer Event: `Transfer(address indexed from, address indexed to, uint256 value)`
    ERC721 Transfer Event: `Transfer(address indexed from, address indexed to, uint256 indexed tokenId)`

    `Event topic` is the same for both events, so they can be indexed together.
     Then we can split them apart based on the `indexed` part as `indexed` elements
     are stored in a different way in the `Ethereum Tx Receipt`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._processed_element_cache = FixedSizeDict(maxlen=40_000)  # Around 3MiB
        self.addresses_cache: Optional[AddressesCache] = None

    @property
    def contract_events(self) -> List[ContractEvent]:
        """
        :return: Web3 ContractEvent to listen to
        """
        return []  # Use custom function to get transfer events

    @property
    def database_field(self):
        return "erc20_block_number"

    @property
    def database_queryset(self) -> QuerySet:
        return SafeContract.objects.all()

    def _do_node_query(
        self,
        addresses: set[ChecksumAddress],
        from_block_number: int,
        to_block_number: int,
    ) -> List[LogReceipt]:
        """
        Override function to call custom `get_total_transfer_history` function

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return:
        """

        # If not too many addresses are provided it's alright to do the filtering in the RPC server
        # Otherwise, get all the ERC20/721 events and filter them here
        parameter_addresses = (
            None if len(addresses) > self.query_chunk_size else addresses
        )

        with self.auto_adjust_block_limit(from_block_number, to_block_number):
            transfer_events = self.ethereum_client.erc20.get_total_transfer_history(
                parameter_addresses,
                from_block=from_block_number,
                to_block=to_block_number,
            )

        if parameter_addresses:
            return [
                transfer_event
                for transfer_event in transfer_events
                if transfer_event["blockHash"]
                != transfer_event["transactionHash"]  # CELO ERC20 rewards
            ]

        # Every ERC20/721 event is returned, we need to filter ourselves
        return [
            transfer_event
            for transfer_event in transfer_events
            if transfer_event["blockHash"]
            != transfer_event["transactionHash"]  # CELO ERC20 rewards
            and (
                transfer_event["args"]["to"] in addresses
                or transfer_event["args"]["from"] in addresses
            )
        ]

    def _process_decoded_element(self, decoded_element: EventData) -> None:
        """
        Not used as `process_elements` is redefined using custom processors

        :param decoded_element:
        :return:
        """
        pass

    def events_to_erc20_transfer(
        self, log_receipts: Sequence[EventData]
    ) -> Iterator[ERC20Transfer]:
        for log_receipt in log_receipts:
            try:
                yield ERC20Transfer.from_decoded_event(log_receipt)
            except ValueError:
                pass

    def events_to_erc721_transfer(
        self, log_receipts: Sequence[EventData]
    ) -> Iterator[ERC721Transfer]:
        for log_receipt in log_receipts:
            try:
                yield ERC721Transfer.from_decoded_event(log_receipt)
            except ValueError:
                pass

    def events_to_safe_relevant_transaction(
        self, log_receipts: Sequence[EventData]
    ) -> Iterator[SafeRelevantTransaction]:
        for log_receipt in log_receipts:
            try:
                yield from SafeRelevantTransaction.from_erc20_721_event(log_receipt)
            except ValueError:
                pass

    def process_elements(
        self, log_receipts: Sequence[EventData]
    ) -> List[TokenTransfer]:
        """
        Process all events found by `find_relevant_elements`

        :param log_receipts: Events to store in database
        :return: List of `TokenTransfer` already stored in database
        """
        tx_hashes = OrderedDict.fromkeys(
            [log_receipt["transactionHash"] for log_receipt in log_receipts]
        ).keys()
        if not tx_hashes:
            return []
        else:
            logger.debug("Prefetching and storing %d ethereum txs", len(tx_hashes))
            self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
            logger.debug("End prefetching and storing of ethereum txs")

            logger.debug("Storing TokenTransfer objects")
            not_processed_log_receipts = [
                log_receipt
                for log_receipt in log_receipts
                if not self.element_already_processed_checker.is_processed(
                    log_receipt["transactionHash"],
                    log_receipt["blockHash"],
                    log_receipt["logIndex"],
                )
            ]
            logger.debug("Storing Transfer Events")
            result_erc20 = ERC20Transfer.objects.bulk_create_from_generator(
                self.events_to_erc20_transfer(not_processed_log_receipts),
                ignore_conflicts=True,
            )
            logger.debug("Stored %d ERC20 Events", result_erc20)
            result_erc721 = ERC721Transfer.objects.bulk_create_from_generator(
                self.events_to_erc721_transfer(not_processed_log_receipts),
                ignore_conflicts=True,
            )
            logger.debug("Stored %d ERC721 Events", result_erc721)
            result_safe_relevant_transaction = (
                SafeRelevantTransaction.objects.bulk_create_from_generator(
                    self.events_to_safe_relevant_transaction(
                        not_processed_log_receipts
                    ),
                    ignore_conflicts=True,
                )
            )
            logger.debug(
                "Stored %d Safe Relevant Transactions", result_safe_relevant_transaction
            )
            logger.debug("Marking events as processed")
            for log_receipt in not_processed_log_receipts:
                self.element_already_processed_checker.mark_as_processed(
                    log_receipt["transactionHash"],
                    log_receipt["blockHash"],
                    log_receipt["logIndex"],
                )
            logger.debug("Marked events as processed")
            return range(
                result_erc20 + result_erc721
            )  # TODO Hack to prevent returning `TokenTransfer` and using too much RAM

    def get_almost_updated_addresses(
        self, current_block_number: int
    ) -> set[ChecksumAddress]:
        """

        :param current_block_number:
        :return: Monitored addresses to be processed
        """

        logger.debug("%s: Retrieving monitored addresses", self.__class__.__name__)

        last_checked: Optional[datetime.datetime]
        if self.addresses_cache:
            # Only search for the new addresses
            query = self.database_queryset.filter(
                created__gte=self.addresses_cache.last_checked
            )
            addresses = self.addresses_cache.addresses
            last_checked = self.addresses_cache.last_checked
        else:
            query = self.database_queryset.all()
            addresses = set()
            last_checked = None

        for created, address in query.values_list("created", "address").order_by(
            "created"
        ):
            addresses.add(address)

        try:
            last_checked = created
        except NameError:  # database query empty, `created` not defined
            pass

        if last_checked:
            # Don't use caching if list is empty
            self.addresses_cache = AddressesCache(addresses, last_checked)

        logger.debug("%s: Retrieved monitored addresses", self.__class__.__name__)
        return addresses

    def get_not_updated_addresses(self, current_block_number: int) -> EmptyQuerySet:
        """
        :param current_block_number:
        :return: Monitored addresses to be processed
        """
        return self.database_queryset.none()

    def get_from_block_number(
        self, addresses: Optional[set[ChecksumAddress]] = None
    ) -> Optional[int]:
        """
        :param addresses:
        :return: `block_number` to resume indexing from using `IndexingStatus` table
        """
        return IndexingStatus.objects.get_erc20_721_indexing_status().block_number

    def update_monitored_addresses(
        self,
        addresses: set[ChecksumAddress],
        from_block_number: int,
        to_block_number: int,
    ) -> bool:
        """
        Update `IndexingStatus` table with the next block to be processed.

        :param addresses:
        :param from_block_number:
        :param to_block_number:
        :return: `True` if table was updated, `False` otherwise
        """
        # Keep indexing going on the next block
        new_to_block_number = to_block_number + 1
        updated = IndexingStatus.objects.set_erc20_721_indexing_status(
            new_to_block_number, from_block_number=from_block_number
        )
        if not updated:
            logger.warning(
                "%s: Possible reorg - Cannot update erc20_721 indexing status from-block-number=%d to-block-number=%d",
                self.__class__.__name__,
                from_block_number,
                to_block_number,
            )
        return updated
