from logging import getLogger
from typing import List, Set

from gnosis.eth import EthereumClient

from ..models import EthereumEvent

from .transaction_indexer import TransactionIndexer

logger = getLogger(__name__)


class Erc20EventsServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = Erc20EventsService(EthereumClient(settings.ETHEREUM_TRACING_NODE_URL))
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class Erc20EventsService(TransactionIndexer):
    """
    Indexes ERC20 and ERC721 `Transfer` Event (as ERC721 has the same topic)
    """
    @property
    def database_field(self):
        return 'erc_20_block_number'

    def find_relevant_elements(self, addresses: List[str], from_block_number: int,
                                to_block_number: int) -> Set[str]:
        """
        Search for tx hashes with erc20 transfer events (`from` and `to`) of a `safe_address`
        :param addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: Tx hashes of txs with relevant erc20 transfer events for the `addresses`
        """
        logger.debug('Searching for erc20 txs from block-number=%d to block-number=%d - Safes=%s',
                     from_block_number, to_block_number, addresses)

        # It will get erc721 events, as `topic` is the same
        erc20_transfer_events = self.ethereum_client.erc20.get_total_transfer_history(addresses,
                                                                                      from_block=from_block_number,
                                                                                      to_block=to_block_number)
        # Log INFO if erc events found, DEBUG otherwise
        logger_fn = logger.info if erc20_transfer_events else logger.debug
        logger_fn('Found %d relevant erc20 txs between block-number=%d and block-number=%d. Safes=%s',
                  len(erc20_transfer_events), from_block_number, to_block_number, addresses)

        return set([event['transactionHash'] for event in erc20_transfer_events])

    def process_element(self, tx_hash: str) -> List[EthereumEvent]:
        """
        Search on Ethereum and store erc20 transfer events for provided `tx_hash`
        :param tx_hash:
        :return: List of `Erc20TransferEvent` already stored in database
        """
        ethereum_tx = self.create_or_update_ethereum_tx(tx_hash)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
        decoded_logs = self.ethereum_client.erc20.decode_logs(tx_receipt.logs)
        return [EthereumEvent.objects.get_or_create_erc20_or_721_event(event) for event in decoded_logs]
