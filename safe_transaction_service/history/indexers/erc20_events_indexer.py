import operator
from collections import OrderedDict
from logging import getLogger
from typing import Iterator, List, Optional, Sequence

from django.db.models import QuerySet

from cache_memoize import cache_memoize
from cachetools import cachedmethod
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from web3.contract import ContractEvent
from web3.exceptions import BadFunctionCallOutput
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient

from safe_transaction_service.tokens.models import Token

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
            from django.conf import settings

            cls.instance = Erc20EventsIndexer(
                EthereumClient(settings.ETHEREUM_NODE_URL)
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class Erc20EventsIndexer(EventsIndexer):
    _cache_is_erc20 = {}

    """
    Indexes ERC20 and ERC721 `Transfer` Event (as ERC721 has the same topic)
    """

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
            return transfer_events

        # Every ERC20/721 event is returned, we need to filter ourselves
        addresses_set = set(addresses)
        return [
            transfer_event
            for transfer_event in transfer_events
            if transfer_event["args"]["to"] in addresses_set
            or transfer_event["args"]["from"] in addresses_set
        ]

    @cachedmethod(cache=operator.attrgetter("_cache_is_erc20"))
    @cache_memoize(60 * 60 * 24, prefix="erc20-events-indexer-is-erc20")  # 1 day
    def _is_erc20(self, token_address: str) -> bool:
        try:
            token = Token.objects.get(address=token_address)
            return token.is_erc20()
        except Token.DoesNotExist:
            try:
                decimals = self.ethereum_client.erc20.get_decimals(token_address)
                return decimals is not None
            except (ValueError, BadFunctionCallOutput, DecodingError):
                return False

    def _process_decoded_element(self, event: EventData) -> EventData:
        """
        :param event: Be careful, it will be modified instead of copied
        :return: The same event if it's a ERC20/ERC721. Tries to tell apart if it's not defined (`unknown` instead
            of `value` or `tokenId`)
        """
        event_args = event["args"]
        if "unknown" in event_args:  # Not standard event
            event_args["value"] = event_args.pop("unknown")

        if self._is_erc20(event["address"]):
            if "tokenId" in event_args:
                event_args["value"] = event_args.pop("tokenId")
        else:
            if "value" in event_args:
                event_args["tokenId"] = event_args.pop("value")
        return event

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
            result_erc20 = ERC20Transfer.objects.bulk_create_from_generator(
                self.events_to_erc20_transfer(log_receipts), ignore_conflicts=True
            )
            result_erc721 = ERC721Transfer.objects.bulk_create_from_generator(
                self.events_to_erc721_transfer(log_receipts), ignore_conflicts=True
            )
            logger.debug("Stored TokenTransfer objects")
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

    def update_monitored_address(
        self, addresses: Sequence[str], from_block_number: int, to_block_number: int
    ) -> int:
        return int(
            IndexingStatus.objects.set_erc20_721_indexing_status(to_block_number)
        )
