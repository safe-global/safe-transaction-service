# SPDX-License-Identifier: FSL-1.1-MIT
from logging import getLogger

from eth_typing import HexStr
from hexbytes import HexBytes
from safe_eth.util.util import to_0x_hex_str

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

    def get_key(
        self, tx_hash: HexStr | bytes, block_hash: HexStr | bytes | None, index: int
    ) -> bytes:
        tx_hash_bytes = HexBytes(tx_hash)
        block_hash_bytes = HexBytes(block_hash or 0)
        index_bytes = HexBytes(index)
        return tx_hash_bytes + block_hash_bytes + index_bytes

    def is_processed(
        self, tx_hash: HexStr | bytes, block_hash: HexStr | bytes | None, index: int = 0
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
        self, tx_hash: HexStr | bytes, block_hash: HexStr | bytes | None, index: int = 0
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
                to_0x_hex_str(HexBytes(tx_hash)),
                to_0x_hex_str(HexBytes(block_hash or 0)),
                index,
            )
            return False
        else:
            logger.debug(
                "Marking element with tx-hash=%s on block=%s with index=%d as processed",
                to_0x_hex_str(HexBytes(tx_hash)),
                to_0x_hex_str(HexBytes(block_hash or 0)),
                index,
            )
            self._processed_element_cache[tx_id] = None
            return True
