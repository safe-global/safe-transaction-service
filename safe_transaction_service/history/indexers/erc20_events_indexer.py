import operator
from collections import OrderedDict
from logging import getLogger
from typing import List, Sequence

from cache_memoize import cache_memoize
from cachetools import cachedmethod
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from web3.contract import ContractEvent
from web3.exceptions import BadFunctionCallOutput
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient

from ..models import EthereumEvent, SafeContract
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
        parameter_addresses = None if len(addresses) > 300 else addresses
        transfer_events = self.ethereum_client.erc20.get_total_transfer_history(
            parameter_addresses, from_block=from_block_number, to_block=to_block_number
        )
        if parameter_addresses:
            return transfer_events  # Results are already filtered
        else:
            addresses = set(addresses)  # Faster to check with `in`
            return [
                transfer_event
                for transfer_event in transfer_events
                if transfer_event["args"]["to"] in addresses
                or transfer_event["args"]["from"] in addresses
            ]

    @cachedmethod(cache=operator.attrgetter("_cache_is_erc20"))
    @cache_memoize(60 * 60 * 24, prefix="erc20-events-indexer-is-erc20")  # 1 day
    def _is_erc20(self, token_address: str) -> bool:
        try:
            decimals = self.ethereum_client.erc20.get_decimals(token_address)
            return decimals >= 0
        except (ValueError, BadFunctionCallOutput, DecodingError):
            return False

    def _process_decoded_element(self, event: EventData) -> EventData:
        """
        :param event: Be careful, it will be modified instead of copied
        :return: The same event if it's a ERC20/ERC721. Tries to tell apart if it's not defined (`unknown` instead
            of `value` or `tokenId`)
        """
        event_args = event["args"]
        if (
            "unknown" in event_args
        ):  # Not standard event, trying to tell apart ERC20 from ERC721
            logger.info(
                "Cannot tell apart erc20 or 721 for token-address=%s - Checking token decimals",
                event["address"],
            )
            value = event_args.pop("unknown")
            if self._is_erc20(event["address"]):
                event_args["value"] = value
            else:
                event_args["tokenId"] = value
        return event

    def process_elements(
        self, log_receipts: Sequence[EventData]
    ) -> List[EthereumEvent]:
        """
        Process all events found by `find_relevant_elements`

        :param log_receipts: Events to store in database
        :return: List of `EthereumEvent` already stored in database
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
            logger.debug("Creating EthereumEvent objects")
            ethereum_events = (
                EthereumEvent.objects.from_decoded_event(log_receipt)
                for log_receipt in log_receipts
            )
            logger.debug("Storing EthereumEvent objects")
            result = EthereumEvent.objects.bulk_create_from_generator(
                ethereum_events, ignore_conflicts=True
            )
            logger.debug("Stored EthereumEvent objects")
            return range(
                result
            )  # TODO Hack to prevent returning `EthereumEvent` and using too much RAM
