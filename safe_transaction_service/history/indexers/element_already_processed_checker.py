from logging import getLogger
from typing import Optional

from hexbytes import HexBytes

from safe_transaction_service.utils.utils import FixedSizeDict

logger = getLogger(__name__)


class ElementAlreadyProcessedChecker:
    """
    Keeps a cache of already processed transactions and events
    """

    def __init__(self):
        self._processed_element_cache = FixedSizeDict(maxlen=40_000)  # Around 3MiB

    def clear(self) -> None:
        return self._processed_element_cache.clear()

    def get_key(self, tx_hash: HexBytes, block_hash: HexBytes, index: int) -> HexBytes:
        tx_hash = HexBytes(tx_hash)
        block_hash = HexBytes(block_hash or 0)
        index = HexBytes(index)
        return tx_hash + block_hash + index

    def is_processed(
        self, tx_hash: HexBytes, block_hash: Optional[HexBytes], index: int = 0
    ) -> bool:
        """
        :param tx_hash:
        :param block_hash:
        :param index: Only for events
        :return: ``True`` if element was processed, ``False`` otherwise
        """
        tx_id = self.get_key(tx_hash, block_hash, index)
        return tx_id in self._processed_element_cache

    def mark_as_processed(
        self, tx_hash: HexBytes, block_hash: Optional[HexBytes], index: int = 0
    ) -> bool:
        """
        Mark element as processed if it is not already marked

        :param tx_hash:
        :param block_hash:
        :param index: Only for events
        :return: ``True`` if element was marked as processed, ``False`` if it was marked already
        """
        tx_id = self.get_key(tx_hash, block_hash, index)

        if tx_id in self._processed_element_cache:
            logger.debug(
                "Element with tx-hash=%s on block=%s with index=%d was already processed",
                tx_hash.hex(),
                block_hash.hex(),
                index,
            )
            return False
        else:
            logger.debug(
                "Marking element with tx-hash=%s on block=%s with index=%d as processed",
                tx_hash.hex(),
                block_hash.hex(),
                index,
            )
            self._processed_element_cache[tx_id] = None
            return True
