import contextlib
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

import gevent
import requests
from celery import app
from celery.app.task import Task as CeleryTask
from celery.signals import celeryd_init, worker_shutting_down
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from safe_transaction_service.contracts.tasks import \
    index_contracts_metadata_task

from .indexers import (Erc20EventsIndexerProvider, InternalTxIndexerProvider,
                       ProxyFactoryIndexerProvider)
from .indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider
from .models import (InternalTxDecoded, MultisigTransaction, SafeStatus,
                     WebHook, WebHookType)
from .services import IndexServiceProvider, ReorgService, ReorgServiceProvider
from .utils import close_gevent_db_connection, get_redis

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 15  # 15 minutes
SOFT_TIMEOUT = 60 * 10  # 10 minutes
ACTIVE_LOCKS: Set[str] = set()  # Active redis locks, release them when worker stops
WORKER_STOPPED = set()  # Worker status


@celeryd_init.connect
def configure_workers(sender=None, conf=None, **kwargs):
    def patch_psycopg():
        """
        Patch postgresql to be friendly with gevent
        """
        try:
            from psycogreen.gevent import patch_psycopg
            logger.info('Patching psycopg for gevent')
            patch_psycopg()
        except ImportError:
            pass
    patch_psycopg()


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning('Worker shutting down')
    gevent.spawn(shutdown_worker)  # If not raises a `BlockingSwitchOutError`


def shutdown_worker():
    WORKER_STOPPED.add(True)
    if ACTIVE_LOCKS:
        logger.warning('Force releasing of redis locks %s', ACTIVE_LOCKS)
        get_redis().delete(*ACTIVE_LOCKS)
        logger.warning('Released redis locks')
    else:
        logger.warning('No redis locks to release')


@contextlib.contextmanager
def ony_one_running_task(task: CeleryTask,
                         lock_name_suffix: Optional[str] = None,
                         blocking_timeout: int = 1,
                         lock_timeout: Optional[int] = LOCK_TIMEOUT):
    """
    Ensures one running task at the same, using `task` name as a unique key
    :param task: CeleryTask
    :param lock_name_suffix: A suffix for the lock name, in the case that the same task can be run at the same time
    when it has different arguments
    :param blocking_timeout: Waiting blocking timeout, it should be as small as possible to the worker can release
    the task
    :param lock_timeout: How long the lock will be stored, in case worker is halted so key is not stored forever
    in Redis
    :return: Instance of redis `Lock`
    :raises: LockError if lock cannot be acquired
    """
    if WORKER_STOPPED:
        raise LockError('Worker is stopping')
    redis = get_redis()
    lock_name = f'tasks:{task.name}'
    if lock_name_suffix:
        lock_name = f'{lock_name}:{lock_name_suffix}'
    with redis.lock(lock_name, blocking_timeout=blocking_timeout, timeout=lock_timeout) as lock:
        ACTIVE_LOCKS.add(lock_name)
        yield lock
        ACTIVE_LOCKS.remove(lock_name)
        close_gevent_db_connection()  # Need for django-db-geventpool


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def index_new_proxies_task(self) -> Optional[int]:
    """
    :return: Number of proxies created
    """
    with contextlib.suppress(LockError):
        with ony_one_running_task(self):
            logger.info('Start indexing of new proxies')
            number_proxies = ProxyFactoryIndexerProvider().start()
            if number_proxies:
                logger.info('Indexed new %d proxies', number_proxies)
                return number_proxies


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def index_internal_txs_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    with contextlib.suppress(LockError):
        with ony_one_running_task(self):
            logger.info('Start indexing of internal txs')
            number_traces = InternalTxIndexerProvider().start()
            logger.info('Find internal txs task processed %d traces', number_traces)
            if number_traces:
                logger.info('Calling task to process decoded traces')
                process_decoded_internal_txs_task.delay()
            return number_traces


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def index_erc20_events_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """
    with contextlib.suppress(LockError):
        with ony_one_running_task(self):
            logger.info('Start indexing of erc20/721 events')
            number_events = Erc20EventsIndexerProvider().start()
            logger.info('Indexing of erc20/721 events task processed %d events', number_events)
            return number_events


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def process_decoded_internal_txs_task(self) -> Optional[int]:
    try:
        with ony_one_running_task(self):
            count = InternalTxDecoded.objects.pending_for_safes().count()
            if not count:
                logger.info('No decoded internal txs to process')
            else:
                logger.info('%d decoded internal txs to process', count)
                for safe_to_process in InternalTxDecoded.objects.safes_pending_to_be_processed():
                    process_decoded_internal_txs_for_safe_task.delay(safe_to_process)
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, task_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_for_safe_task(self, safe_address: str) -> Optional[int]:
    """
    Process decoded internal txs for one Safe. Processing decoded transactions is very slow and this way multiple
    Safes can be processed at the same time
    :param safe_address:
    :return:
    """
    try:
        with ony_one_running_task(self, lock_name_suffix=safe_address):
            logger.info('Start processing decoded internal txs for safe %s', safe_address)
            number_processed = 0
            batch = 100  # Process at most 100 decoded transactions for a single Safe
            tx_processor: SafeTxProcessor = SafeTxProcessorProvider()
            # Use slicing for memory issues
            while True:
                # Check if something is wrong during indexing
                safe_status = SafeStatus.objects.last_for_address(safe_address)
                if safe_status and safe_status.is_corrupted():
                    tx_processor.clear_cache()
                    message = f'A problem was found in SafeStatus with nonce={safe_status.nonce} ' \
                              f'on internal-tx-id={safe_status.internal_tx_id} ' \
                              f'for safe-address={safe_address}, reindexing'
                    logger.warning(message)
                    IndexServiceProvider().reindex_addresses([safe_address])
                    raise ValueError(message)

                internal_txs_decoded = InternalTxDecoded.objects.pending_for_safe(safe_address)[:batch]
                if not internal_txs_decoded:
                    break
                number_processed += len(tx_processor.process_decoded_transactions(internal_txs_decoded))
                tx_processor.clear_cache()  # TODO Fix this properly
                logger.info('Processed %d decoded transactions', number_processed)
            if number_processed:
                logger.info('%d decoded internal txs successfully processed for safe %s',
                            number_processed, safe_address)
                return number_processed
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def check_reorgs_task(self) -> Optional[int]:
    """
    :return: Number of oldest block with reorg detected. `None` if not reorg found
    """
    try:
        with ony_one_running_task(self):
            logger.info('Start checking of reorgs')
            reorg_service: ReorgService = ReorgServiceProvider()
            first_reorg_block_number = reorg_service.check_reorgs()
            if first_reorg_block_number:
                logger.warning('Reorg found for block-number=%d', first_reorg_block_number)
                # Stopping running tasks is not possible with gevent
                reorg_service.recover_from_reorg(first_reorg_block_number)
                return first_reorg_block_number
    except LockError:
        pass


@app.shared_task()
def send_webhook_task(address: Optional[str], payload: Dict[str, Any]) -> int:
    if not (address and payload):
        return 0

    try:
        webhooks = WebHook.objects.matching_for_address(address)
        if not webhooks:
            return 0

        sent_requests = 0
        webhook_type = WebHookType[payload['type']]
        for webhook in webhooks:
            if not webhook.is_valid_for_webhook_type(webhook_type):
                continue

            parsed_url = urlparse(webhook.url)
            host = f'{parsed_url.scheme}://{parsed_url.netloc}'
            if webhook.address:
                logger.info('Sending webhook for address=%s host=%s and payload=%s', address, host, payload)
            else:  # Generic WebHook
                logger.info('Sending webhook for host=%s and payload=%s', host, payload)

            r = requests.post(webhook.url, json=payload)
            if not r.ok:
                logger.warning('Failed status code %d posting to host=%s with content=%s',
                               r.status_code, host, r.content)

            sent_requests += 1
        return sent_requests
    finally:
        close_gevent_db_connection()


@app.shared_task()
def index_contract_metadata() -> int:
    """
    Call `index_contracts_metadata_task` in the `contracts` app to index contracts with missing metadata
    :return:
    """
    batch = 100
    processed = 0

    while True:
        addresses = MultisigTransaction.objects.not_indexed_metadata_contract_addresses()[:batch]
        if not addresses:
            break
        else:
            index_contracts_metadata_task.delay(list(addresses))
            processed += len(addresses)
    return processed
