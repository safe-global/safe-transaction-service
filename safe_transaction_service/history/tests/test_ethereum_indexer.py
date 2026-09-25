# SPDX-License-Identifier: FSL-1.1-MIT
import os
from unittest import mock

from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from ...utils.redis import get_redis
from ..indexers import ethereum_indexer
from ..indexers.safe_events_indexer import SafeEventsIndexer, SafeEventsIndexerProvider
from ..services.index_service import TransactionNotFoundException
from .factories import SafeMasterCopyFactory


class TestEthereumIndexerStuckTxAlert(EthereumTestCaseMixin, TestCase):
    """
    `TransactionNotFoundException` is raised by all the tx/receipt fetching paths
    used by the event indexers. These tests exercise the shared handling of that
    exception in `EthereumIndexer.process_addresses`.
    """

    def setUp(self) -> None:
        self.safe_events_indexer = SafeEventsIndexer(
            self.ethereum_client, confirmations=0, blocks_to_reindex_again=0
        )
        self.safe_master_copy = SafeMasterCopyFactory(
            address=Account.create().address, l2=True
        )
        self.addresses = {self.safe_master_copy.address}

    def tearDown(self) -> None:
        SafeEventsIndexerProvider.del_singleton()
        redis = get_redis()
        for key in redis.scan_iter("ethereum-indexer:stuck-tx:*"):
            redis.delete(key)

    def _redis_key(self, tx_hash: bytes) -> str:
        return (
            f"ethereum-indexer:stuck-tx:{self.safe_events_indexer.__class__.__name__}:"
            f"{to_0x_hex_str(HexBytes(tx_hash))}"
        )

    def test_transient_failure_does_not_alert(self):
        """
        A single failure fetching a tx must not log a critical alert: it is
        indistinguishable from a transient RPC hiccup.
        """
        tx_hash = HexBytes(os.urandom(32))
        exception = TransactionNotFoundException("Cannot find tx", tx_hash=tx_hash)

        with (
            self.settings(ETH_INDEX_STUCK_TX_MAX_CONSECUTIVE_FAILURES=3),
            mock.patch.object(
                self.safe_events_indexer,
                "find_relevant_elements",
                side_effect=exception,
            ),
            mock.patch.object(ethereum_indexer.logger, "critical") as critical_mock,
        ):
            with self.assertRaises(TransactionNotFoundException):
                self.safe_events_indexer.process_addresses(self.addresses)

        critical_mock.assert_not_called()
        self.assertEqual(int(get_redis().get(self._redis_key(tx_hash))), 1)

    def test_repeated_failure_alerts_once_threshold_is_reached(self):
        """
        The same tx failing across several runs must reach the configured
        threshold before a critical alert is logged, and the alert must include
        the tx hash, the block range and the failure count.
        """
        tx_hash = HexBytes(os.urandom(32))
        exception = TransactionNotFoundException("Cannot find tx", tx_hash=tx_hash)
        max_consecutive_failures = 3

        with (
            self.settings(
                ETH_INDEX_STUCK_TX_MAX_CONSECUTIVE_FAILURES=max_consecutive_failures
            ),
            mock.patch.object(
                self.safe_events_indexer,
                "find_relevant_elements",
                side_effect=exception,
            ),
            mock.patch.object(
                self.safe_events_indexer,
                "get_block_numbers_for_search",
                return_value=(10, 20),
            ),
            mock.patch.object(ethereum_indexer.logger, "critical") as critical_mock,
        ):
            for _ in range(max_consecutive_failures - 1):
                with self.assertRaises(TransactionNotFoundException):
                    self.safe_events_indexer.process_addresses(self.addresses)
            critical_mock.assert_not_called()

            with self.assertRaises(TransactionNotFoundException):
                self.safe_events_indexer.process_addresses(self.addresses)

        critical_mock.assert_called_once()
        self.assertEqual(
            critical_mock.call_args.args[1:],
            (
                SafeEventsIndexer.__name__,
                to_0x_hex_str(tx_hash),
                10,
                20,
                max_consecutive_failures,
            ),
        )
        self.assertEqual(
            int(get_redis().get(self._redis_key(tx_hash))), max_consecutive_failures
        )

    def test_repeated_failure_alerts_again_after_another_threshold_worth_of_failures(
        self,
    ):
        """
        The alert must repeat every `max_consecutive_failures` failures instead of
        firing only once, so on-call keeps getting a signal while the tx stays
        stuck, without logging a critical on every single retry.
        """
        tx_hash = HexBytes(os.urandom(32))
        exception = TransactionNotFoundException("Cannot find tx", tx_hash=tx_hash)
        max_consecutive_failures = 2

        with (
            self.settings(
                ETH_INDEX_STUCK_TX_MAX_CONSECUTIVE_FAILURES=max_consecutive_failures
            ),
            mock.patch.object(
                self.safe_events_indexer,
                "find_relevant_elements",
                side_effect=exception,
            ),
            mock.patch.object(ethereum_indexer.logger, "critical") as critical_mock,
        ):
            for _ in range(2 * max_consecutive_failures):
                with self.assertRaises(TransactionNotFoundException):
                    self.safe_events_indexer.process_addresses(self.addresses)

        self.assertEqual(critical_mock.call_count, 2)
