from collections import OrderedDict
from logging import getLogger
from typing import Iterator, List, Optional, Sequence

from django.db.models import QuerySet

from eth_typing import ChecksumAddress
from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient

from ...utils.utils import FixedSizeDict
from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    IndexingStatus,
    MonitoredAddress,
    SafeContract,
    TokenTransfer,
)
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


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

    As `event topic` is the same both events can be indexed together, and then tell
    apart based on the `indexed` part as `indexed` elements are stored in a different way in the
    `ethereum tx receipt`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._processed_element_cache = FixedSizeDict(maxlen=40_000)  # Around 3MiB

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
    def database_queryset(self):
        return SafeContract.objects.all()

    def _do_node_query(
        self,
        addresses: List[ChecksumAddress],
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

        # If not too much addresses it's alright to filter in the RPC server
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
                != transfer_event["transactionHash"]  # CELO ERC20 indexing
            ]

        # Every ERC20/721 event is returned, we need to filter ourselves
        addresses_set = set(addresses)
        return [
            transfer_event
            for transfer_event in transfer_events
            if transfer_event["blockHash"]
            != transfer_event["transactionHash"]  # CELO ERC20 indexing
            and (
                transfer_event["args"]["to"] in addresses_set
                or transfer_event["args"]["from"] in addresses_set
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
            result_erc20 = ERC20Transfer.objects.bulk_create_from_generator(
                self.events_to_erc20_transfer(not_processed_log_receipts),
                ignore_conflicts=True,
            )
            result_erc721 = ERC721Transfer.objects.bulk_create_from_generator(
                self.events_to_erc721_transfer(not_processed_log_receipts),
                ignore_conflicts=True,
            )
            logger.debug("Stored TokenTransfer objects")
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
    ) -> QuerySet[MonitoredAddress]:
        """

        :param current_block_number:
        :return: Monitored addresses to be processed
        """

        logger.debug("%s: Retrieving monitored addresses", self.__class__.__name__)

        addresses = self.database_queryset.all()

        logger.debug("%s: Retrieved monitored addresses", self.__class__.__name__)
        return addresses

    def get_not_updated_addresses(
        self, current_block_number: int
    ) -> QuerySet[MonitoredAddress]:
        """
        :param current_block_number:
        :return: Monitored addresses to be processed
        """
        return []

    def get_minimum_block_number(
        self, addresses: Optional[Sequence[str]] = None
    ) -> Optional[int]:
        return IndexingStatus.objects.get_erc20_721_indexing_status().block_number

    def update_monitored_addresses(
        self, addresses: Sequence[str], from_block_number: int, to_block_number: int
    ) -> bool:
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
