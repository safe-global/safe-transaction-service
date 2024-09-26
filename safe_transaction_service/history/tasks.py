import contextlib
import dataclasses
import datetime
import json
import random
from typing import Optional, Tuple

from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress
from redis.exceptions import LockError

from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from ..utils.tasks import LOCK_TIMEOUT, SOFT_TIMEOUT, only_one_running_task
from .indexers import (
    Erc20EventsIndexerProvider,
    FindRelevantElementsException,
    InternalTxIndexerProvider,
    ProxyFactoryIndexerProvider,
    SafeEventsIndexerProvider,
)
from .models import EthereumBlock, InternalTxDecoded, MultisigTransaction, SafeContract
from .services import (
    CollectiblesServiceProvider,
    IndexingException,
    IndexService,
    IndexServiceProvider,
    ReorgService,
    ReorgServiceProvider,
)
from .services.collectibles_service import (
    Collectible,
    CollectibleWithMetadata,
    MetadataRetrievalExceptionTimeout,
)

logger = get_task_logger(__name__)


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def check_reorgs_task(self) -> Optional[int]:
    """
    :return: Number of the oldest block with reorg detected. `None` if not reorg found
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start checking of reorgs")
            reorg_service: ReorgService = ReorgServiceProvider()
            reorg_block_number = reorg_service.check_reorgs()
            if not reorg_block_number:
                logger.info("No reorg was found")
                return None
            logger.warning("Reorg found for block-number=%d", reorg_block_number)
            # Stopping running tasks is not possible with gevent
            reorg_service.recover_from_reorg(reorg_block_number)
            return reorg_block_number


@app.shared_task(soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def check_sync_status_task() -> bool:
    """
    Check indexing status of the service
    """
    if is_service_synced := IndexServiceProvider().is_service_synced():
        logger.info("Service is synced")
    else:
        logger.error("Service is out of sync")

    return is_service_synced


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_erc20_events_task(self) -> Optional[Tuple[int, int]]:
    """
    Find and process ERC20/721 events for monitored addresses

    :return: Tuple Number of addresses processed, number of blocks processed
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of erc20/721 events")
            (
                number_events,
                number_of_blocks_processed,
            ) = Erc20EventsIndexerProvider().start()
            logger.debug(
                "Indexing of erc20/721 events task processed %d events", number_events
            )
            return number_events, number_of_blocks_processed


@app.shared_task
@close_gevent_db_connection_decorator
def index_erc20_events_out_of_sync_task(
    block_process_limit: Optional[int] = None,
    block_process_limit_max: Optional[int] = None,
    addresses: Optional[list[ChecksumAddress]] = None,
    number_of_addresses: Optional[int] = 100,
) -> Optional[int]:
    """
    Find and process ERC20/721 events for monitored addresses out of sync (really behind)

    :return: Number of addresses processed
    """
    erc20_events_indexer = Erc20EventsIndexerProvider()
    if block_process_limit:
        erc20_events_indexer.block_process_limit = block_process_limit
    if block_process_limit_max:
        erc20_events_indexer.block_process_limit_max = block_process_limit_max

    current_block_number = erc20_events_indexer.ethereum_client.current_block_number
    addresses = (
        set(addresses)
        if addresses
        else set(
            list(
                erc20_events_indexer.get_almost_updated_addresses(current_block_number)
            )[:number_of_addresses]
        )
    )

    if not addresses:
        logger.info("No addresses to process")
    else:
        logger.info(
            "Start indexing of erc20/721 events for out of sync addresses %s",
            addresses,
        )
        updated = False
        number_events_processed = 0
        while not updated:
            try:
                (
                    events_processed,
                    _,
                    _,
                    updated,
                ) = erc20_events_indexer.process_addresses(
                    addresses, current_block_number
                )
                number_events_processed += len(events_processed)
            except FindRelevantElementsException:
                pass

        logger.info(
            "Indexing of erc20/721 events for out of sync addresses task processed %d events",
            number_events_processed,
        )
        return number_events_processed


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_internal_txs_task(self) -> Optional[Tuple[int, int]]:
    """
    Find and process internal txs for monitored addresses
    :return: Tuple of number of addresses processed and number of blocks processed
    """

    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of internal txs")
            (
                number_traces,
                number_of_blocks_processed,
            ) = InternalTxIndexerProvider().start()
            logger.info("Find internal txs task processed %d traces", number_traces)
            if number_traces:
                logger.info("Calling task to process decoded traces")
                process_decoded_internal_txs_task.delay()
            return number_traces, number_of_blocks_processed


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_new_proxies_task(self) -> Optional[Tuple[int, int]]:
    """
    :return: Tuple of number of proxies created and number of blocks processed
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of new proxies")
            (
                number_proxies,
                number_of_blocks_processed,
            ) = ProxyFactoryIndexerProvider().start()
            logger.info("Proxy indexing found %d proxies", number_proxies)
            return number_proxies, number_of_blocks_processed


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_safe_events_task(self) -> Optional[Tuple[int, int]]:
    """
    Find and process for monitored addresses
    :return: Tuple of number of addresses processed and number of blocks processed
    """

    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of Safe events")
            number, number_of_blocks_processed = SafeEventsIndexerProvider().start()
            logger.info("Find Safe events processed %d events", number)
            if number:
                logger.info("Calling task to process decoded traces")
                process_decoded_internal_txs_task.delay()
            return number, number_of_blocks_processed


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task(self) -> Optional[int]:
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start process decoded internal txs")
            count = 0
            banned_safes = set(SafeContract.objects.get_banned_safes())
            for (
                safe_to_process
            ) in InternalTxDecoded.objects.safes_pending_to_be_processed().iterator():
                if safe_to_process in banned_safes:
                    logger.info(
                        "Ignoring decoded internal txs for banned safe %s",
                        safe_to_process,
                    )
                    # Mark traces as processed so they are not reprocessed all the time
                    # If not, `InternalTxDecoded` index with `decoded=True` can grow to
                    # a point were `safes_pending_to_be_processed` takes minutes to complete
                    InternalTxDecoded.objects.for_safe(
                        safe_to_process
                    ).not_processed().update(processed=True)
                else:
                    count += 1
                    process_decoded_internal_txs_for_safe_task.delay(
                        safe_to_process, reindex_master_copies=True
                    )

            if not count:
                logger.info("No Safes to process")
            else:
                logger.info("%d Safes to process", count)


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_for_safe_task(
    self, safe_address: ChecksumAddress, reindex_master_copies: bool = True
) -> Optional[int]:
    """
    Process decoded internal txs for one Safe. Processing decoded transactions
    could be slow and this way multiple Safes can be processed at the same time

    :param safe_address:
    :param reindex_master_copies: Trigger auto reindexing if a problem is found
    :return: Number of `InternalTxDecoded` processed
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self, lock_name_suffix=safe_address):
            logger.info("[%s] Start processing decoded internal txs", safe_address)
            index_service: IndexService = IndexServiceProvider()
            number_processed = index_service.process_decoded_txs(safe_address)
            logger.info(
                "[%s] Processed %d decoded transactions", safe_address, number_processed
            )
            return number_processed


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def reindex_mastercopies_last_hours_task(self, hours: float = 2.5) -> Optional[int]:
    """
    Reindexes last hours for master copies to prevent indexing issues
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            if ethereum_block := EthereumBlock.objects.oldest_than(
                seconds=60 * 60 * hours
            ).first():
                from_block_number = ethereum_block.number
                to_block_number = (
                    EthereumBlock.objects.order_by("-timestamp").first().number
                )
                assert to_block_number >= from_block_number
                if to_block_number != from_block_number:
                    logger.info(
                        "Reindexing master copies for last %d hours, from-block=%d to-block=%d",
                        hours,
                        from_block_number,
                        to_block_number,
                    )
                    reindex_master_copies_task.delay(
                        from_block_number, to_block_number=to_block_number
                    )


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def reindex_erc20_erc721_last_hours_task(self, hours: float = 2.5) -> Optional[int]:
    """
    Reindexes last hours for erx20 and erc721 to prevent indexing issues
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            if ethereum_block := EthereumBlock.objects.oldest_than(
                seconds=60 * 60 * hours
            ).first():
                from_block_number = ethereum_block.number
                to_block_number = (
                    EthereumBlock.objects.order_by("-timestamp").first().number
                )
                assert to_block_number >= from_block_number
                if to_block_number != from_block_number:
                    logger.info(
                        "Reindexing erc20/721 events for last %d hours, from-block=%d to-block=%d",
                        hours,
                        from_block_number,
                        to_block_number,
                    )
                    reindex_erc20_events_task.delay(
                        from_block_number, to_block_number=to_block_number
                    )


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def reindex_master_copies_task(
    self,
    from_block_number: int,
    to_block_number: Optional[int] = None,
    addresses: Optional[ChecksumAddress] = None,
) -> None:
    """
    Reindexes master copies
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(
            self, lock_name_suffix=str(addresses) if addresses else None
        ):
            index_service = IndexServiceProvider()
            logger.info(
                "Reindexing master copies from-block=%d to-block=%s addresses=%s",
                from_block_number,
                to_block_number,
                addresses,
            )
            index_service.reindex_master_copies(
                from_block_number, to_block_number=to_block_number, addresses=addresses
            )


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def reindex_erc20_events_task(
    self,
    from_block_number: int,
    to_block_number: Optional[int] = None,
    addresses: Optional[ChecksumAddress] = None,
) -> None:
    """
    Reindexes master copies
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(
            self, lock_name_suffix=str(addresses) if addresses else None
        ):
            index_service = IndexServiceProvider()
            logger.info(
                "Reindexing erc20/721 events from-block=%d to-block=%s addresses=%s",
                from_block_number,
                to_block_number,
                addresses,
            )
            index_service.reindex_erc20_events(
                from_block_number, to_block_number=to_block_number, addresses=addresses
            )


@app.shared_task(
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    max_retries=4,
)
def retry_get_metadata_task(
    address: ChecksumAddress, token_id: int
) -> Optional[CollectibleWithMetadata]:
    """
    Retry to get metadata from an uri that during the first try returned a timeout error.

    :param address: collectible address
    :param token_id: collectible id
    """

    collectibles_service = CollectiblesServiceProvider()
    redis_key = collectibles_service.get_metadata_cache_key(address, token_id)
    redis = get_redis()

    # The collectible is shared with the task using Redis.
    # This prevents having the collectible serialized on Redis and also on RabbitMQ.
    if not (binary_collectible_with_metadata_cached := redis.get(redis_key)):
        # If the collectible doesn't exist means that the cache was removed and should wait for first try from the view.
        return None

    collectible_with_metadata_cached = json.loads(
        binary_collectible_with_metadata_cached
    )

    collectible = Collectible(
        collectible_with_metadata_cached["token_name"],
        collectible_with_metadata_cached["token_symbol"],
        collectible_with_metadata_cached["logo_uri"],
        collectible_with_metadata_cached["address"],
        collectible_with_metadata_cached["id"],
        collectible_with_metadata_cached["uri"],
    )

    # Maybe other task already retrieved the metadata
    cached_metadata = collectible_with_metadata_cached["metadata"]
    try:
        metadata = (
            cached_metadata
            if cached_metadata
            else collectibles_service.get_metadata(collectible)
        )
        collectible_with_metadata = CollectibleWithMetadata(
            collectible.token_name,
            collectible.token_symbol,
            collectible.logo_uri,
            collectible.address,
            collectible.id,
            collectible.uri,
            metadata,
        )
        redis.set(
            redis_key,
            json.dumps(dataclasses.asdict(collectible_with_metadata)),
            collectibles_service.COLLECTIBLE_EXPIRATION,
        )
    except MetadataRetrievalExceptionTimeout:
        # Random avoid to run all tasks at the same time
        if (
            retry_get_metadata_task.request.retries
            < retry_get_metadata_task.max_retries
        ):
            retry_get_metadata_task.retry(
                countdown=int(
                    random.uniform(55, 65) * retry_get_metadata_task.request.retries
                )
            )
        else:
            logger.debug(
                "Timeout when getting metadata from %s after %i retries ",
                collectible.uri,
                retry_get_metadata_task.request.retries,
            )
        return None
    return collectible_with_metadata


@app.shared_task()
@close_gevent_db_connection_decorator
def remove_not_trusted_multisig_txs_task(
    time_delta: datetime.timedelta = datetime.timedelta(days=30),
) -> int:
    logger.info("Deleting Multisig Transactions older than %s", time_delta)
    deleted, _ = (
        MultisigTransaction.objects.not_trusted()
        .filter(modified__lt=timezone.now() - time_delta)
        .delete()
    )
    return deleted
