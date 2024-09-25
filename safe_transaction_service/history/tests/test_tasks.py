import dataclasses
import datetime
import json
import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from eth_account import Account

from ...utils.redis import get_redis
from ..indexers import (
    Erc20EventsIndexerProvider,
    InternalTxIndexerProvider,
    SafeEventsIndexerProvider,
)
from ..models import MultisigTransaction, SafeContract, SafeLastStatus, SafeStatus
from ..services import CollectiblesService, CollectiblesServiceProvider, IndexService
from ..services.collectibles_service import CollectibleWithMetadata
from ..tasks import (
    check_reorgs_task,
    check_sync_status_task,
    index_erc20_events_out_of_sync_task,
    index_erc20_events_task,
    index_internal_txs_task,
    index_new_proxies_task,
    index_safe_events_task,
)
from ..tasks import logger as task_logger
from ..tasks import (
    process_decoded_internal_txs_for_safe_task,
    process_decoded_internal_txs_task,
    reindex_erc20_erc721_last_hours_task,
    reindex_mastercopies_last_hours_task,
    remove_not_trusted_multisig_txs_task,
    retry_get_metadata_task,
)
from .factories import (
    EthereumBlockFactory,
    InternalTxDecodedFactory,
    MultisigTransactionFactory,
    SafeContractFactory,
    SafeStatusFactory,
)

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    def _delete_singletons(self):
        Erc20EventsIndexerProvider.del_singleton()
        InternalTxIndexerProvider.del_singleton()
        SafeEventsIndexerProvider.del_singleton()

    def setUp(self):
        self._delete_singletons()

    def tearDown(self):
        self._delete_singletons()

    def test_check_reorgs_task(self):
        self.assertIsNone(check_reorgs_task.delay().result, 0)

    def test_check_sync_status_task(self):
        self.assertFalse(check_sync_status_task.delay().result)

    def test_index_erc20_events_task(self):
        self.assertEqual(index_erc20_events_task.delay().result, (0, 0))

    def test_index_erc20_events_out_of_sync_task(self):
        with self.assertLogs(logger=task_logger) as cm:
            index_erc20_events_out_of_sync_task.delay()
            self.assertIn("No addresses to process", cm.output[0])

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract = SafeContractFactory()
            index_erc20_events_out_of_sync_task.delay()
            addresses = {safe_contract.address}
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {addresses}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

    def test_index_internal_txs_task(self):
        self.assertEqual(index_internal_txs_task.delay().result, (0, 0))

    def test_index_new_proxies_task(self):
        self.assertEqual(index_new_proxies_task.delay().result, (0, 0))

    def test_index_safe_events_task(self):
        self.assertEqual(index_safe_events_task.delay().result, (0, 0))

    @patch.object(IndexService, "reindex_master_copies")
    def test_reindex_mastercopies_last_hours_task(
        self, reindex_master_copies_mock: MagicMock
    ):
        now = timezone.now()
        one_hour_ago = now - datetime.timedelta(hours=1)
        one_day_ago = now - datetime.timedelta(days=1)
        one_week_ago = now - datetime.timedelta(weeks=1)

        reindex_mastercopies_last_hours_task()
        reindex_master_copies_mock.assert_not_called()

        ethereum_block_0 = EthereumBlockFactory(timestamp=one_week_ago)
        ethereum_block_1 = EthereumBlockFactory(timestamp=one_day_ago)
        ethereum_block_2 = EthereumBlockFactory(timestamp=one_hour_ago)
        ethereum_block_3 = EthereumBlockFactory(timestamp=now)

        reindex_mastercopies_last_hours_task()
        reindex_master_copies_mock.assert_called_once_with(
            ethereum_block_1.number,
            to_block_number=ethereum_block_3.number,
            addresses=None,
        )

    @patch.object(IndexService, "reindex_erc20_events")
    def test_reindex_erc20_erc721_last_hours_task(
        self, reindex_erc20_events: MagicMock
    ):
        now = timezone.now()
        one_hour_ago = now - datetime.timedelta(hours=1)
        one_day_ago = now - datetime.timedelta(days=1)
        one_week_ago = now - datetime.timedelta(weeks=1)

        reindex_erc20_erc721_last_hours_task()
        reindex_erc20_events.assert_not_called()

        ethereum_block_0 = EthereumBlockFactory(timestamp=one_week_ago)
        ethereum_block_1 = EthereumBlockFactory(timestamp=one_day_ago)
        ethereum_block_2 = EthereumBlockFactory(timestamp=one_hour_ago)
        ethereum_block_3 = EthereumBlockFactory(timestamp=now)

        reindex_erc20_erc721_last_hours_task()
        reindex_erc20_events.assert_called_once_with(
            ethereum_block_1.number,
            to_block_number=ethereum_block_3.number,
            addresses=None,
        )

    def test_process_decoded_internal_txs_task(self):
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        InternalTxDecodedFactory(
            function_name="setup",
            owner=owner,
            threshold=threshold,
            fallback_handler=fallback_handler,
            internal_tx__to=master_copy,
            internal_tx___from=safe_address,
        )
        process_decoded_internal_txs_task.delay()
        self.assertTrue(SafeContract.objects.get(address=safe_address))
        safe_status = SafeStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.owners, [owner])
        self.assertEqual(safe_status.threshold, threshold)

    def test_process_decoded_internal_txs_for_banned_safe(self):
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        internal_tx_decoded = InternalTxDecodedFactory(
            function_name="setup",
            owner=owner,
            threshold=threshold,
            fallback_handler=fallback_handler,
            internal_tx__to=master_copy,
            internal_tx___from=safe_address,
        )
        SafeContractFactory(address=safe_address, banned=True)
        self.assertTrue(SafeContract.objects.get(address=safe_address).banned)
        self.assertFalse(internal_tx_decoded.processed)
        process_decoded_internal_txs_task.delay()
        internal_tx_decoded.refresh_from_db()
        self.assertTrue(internal_tx_decoded.processed)
        self.assertEqual(SafeStatus.objects.filter(address=safe_address).count(), 0)

    def test_process_decoded_internal_txs_for_safe_task(self):
        safe_status_0 = SafeStatusFactory(nonce=0)
        safe_address = safe_status_0.address
        SafeLastStatus.objects.update_or_create_from_safe_status(safe_status_0)
        with self.assertLogs(logger=task_logger) as cm:
            with patch.object(
                IndexService, "process_decoded_txs", return_value=5
            ) as process_decoded_txs_mock:
                process_decoded_internal_txs_for_safe_task.delay(safe_address)
                process_decoded_txs_mock.assert_called_with(safe_address)
                self.assertIn(
                    f"[{safe_address}] Start processing decoded internal txs",
                    cm.output[0],
                )
                self.assertIn(
                    f"[{safe_address}] Processed 5 decoded transactions",
                    cm.output[1],
                )

    @patch.object(CollectiblesService, "get_metadata", autospec=True, return_value={})
    def test_retry_get_metadata_task(self, get_metadata_mock: MagicMock):
        redis = get_redis()
        collectibles_service = CollectiblesServiceProvider()

        collectible_address = Account.create().address
        collectible_id = 16
        metadata_cache_key = collectibles_service.get_metadata_cache_key(
            collectible_address, collectible_id
        )

        metadata = {
            "name": "Octopus",
            "description": "Atlantic Octopus",
            "image": "http://random-address.org/logo-28.png",
        }

        # Check metadata cannot be retrieved
        get_metadata_mock.assert_not_called()
        self.assertEqual(
            retry_get_metadata_task(collectible_address, collectible_id), None
        )
        # Collectible needs to be cached so metadata can be fetched
        get_metadata_mock.assert_not_called()

        get_metadata_mock.return_value = metadata
        expected = CollectibleWithMetadata(
            "Octopus",
            "OCT",
            "http://random-address.org/logo.png",
            collectible_address,
            collectible_id,
            "http://random-address.org/info-28.json",
            metadata,
        )
        redis.set(
            metadata_cache_key,
            json.dumps(dataclasses.asdict(expected)),
            ex=300,
        )

        self.assertEqual(
            retry_get_metadata_task(collectible_address, collectible_id), expected
        )
        # As metadata was set, task is not requesting it
        get_metadata_mock.assert_not_called()

        collectible_without_metadata = CollectibleWithMetadata(
            "Octopus",
            "OCT",
            "http://random-address.org/logo.png",
            collectible_address,
            collectible_id,
            "http://random-address.org/info-28.json",
            {},
        )
        redis.set(
            metadata_cache_key,
            json.dumps(dataclasses.asdict(collectible_without_metadata)),
            ex=300,
        )

        self.assertEqual(
            retry_get_metadata_task(collectible_address, collectible_id), expected
        )
        # As metadata was not set, task requested it
        get_metadata_mock.assert_called_once()

        self.assertEqual(
            json.loads(redis.get(metadata_cache_key)), dataclasses.asdict(expected)
        )
        redis.delete(metadata_cache_key)

    def test_remove_not_trusted_multisig_txs_task(self):
        self.assertEqual(remove_not_trusted_multisig_txs_task.delay().result, 0)

        MultisigTransactionFactory(trusted=False)
        MultisigTransactionFactory(trusted=True)

        self.assertEqual(remove_not_trusted_multisig_txs_task.delay().result, 0)

        multisig_tx_expected_to_be_deleted = MultisigTransactionFactory(trusted=False)
        multisig_tx_not_expected_to_be_deleted = MultisigTransactionFactory(
            trusted=True, modified=timezone.now() - datetime.timedelta(days=32)
        )
        for multisig_tx in (
            multisig_tx_expected_to_be_deleted,
            multisig_tx_not_expected_to_be_deleted,
        ):
            # Modified is updated by the factory when saved on PostGeneration
            MultisigTransaction.objects.filter(
                safe_tx_hash=multisig_tx.safe_tx_hash
            ).update(modified=timezone.now() - datetime.timedelta(days=32))

        self.assertEqual(MultisigTransaction.objects.count(), 4)
        self.assertEqual(remove_not_trusted_multisig_txs_task.delay().result, 1)

        self.assertFalse(
            MultisigTransaction.objects.filter(
                safe_tx_hash=multisig_tx_expected_to_be_deleted.safe_tx_hash
            ).exists()
        )
