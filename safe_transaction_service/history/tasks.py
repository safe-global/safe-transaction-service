import contextlib
import signal
from typing import Any, Dict, List, NoReturn, Optional, Set
from urllib.parse import urlparse

import requests
from celery import app
from celery.app.task import Context as CeleryContext
from celery.app.task import Task as CeleryTask
from celery.signals import worker_shutting_down
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from ..taskapp.celery import app as celery_app
from .indexers import (Erc20EventsIndexerProvider, InternalTxIndexerProvider,
                       ProxyFactoryIndexerProvider)
from .indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider
from .models import InternalTxDecoded, WebHook, WebHookType
from .services import ReorgService, ReorgServiceProvider
from .utils import close_gevent_db_connection, get_redis

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 15  # 15 minutes
SOFT_TIMEOUT = 60 * 10  # 10 minutes
ACTIVE_LOCKS: Set[str] = set()  # Active redis locks, release them when worker stops


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning('Worker shutting down')
    return shutdown_worker()


def shutdown_worker():
    if ACTIVE_LOCKS:
        logger.warning('Force releasing of redis locks %s', ACTIVE_LOCKS)
        get_redis().delete(*ACTIVE_LOCKS)
        logger.warning('Released redis locks')
    else:
        logger.warning('No redis locks to release')
    return len(BlockchainRunningTaskManager().stop_running_tasks())


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
    redis = get_redis()
    lock_name = f'tasks:{task.name}'
    if lock_name_suffix:
        lock_name = f'{lock_name}:{lock_name_suffix}'
    with redis.lock(lock_name, blocking_timeout=blocking_timeout, timeout=lock_timeout) as lock:
        ACTIVE_LOCKS.add(lock_name)
        yield lock
        ACTIVE_LOCKS.remove(lock_name)


def generate_handler(task_id: str) -> NoReturn:
    def handler(signum, frame):
        shutdown_worker()  # It shouldn't be here, but gevent can catch the sigterm in every task
        logger.warning('Received SIGTERM on task-id=%s', task_id)
        raise OSError(f'Received SIGTERM on task-id={task_id}. Probably a reorg. Task must exit')
    return handler


class BlockchainRunningTaskManager:
    blockchain_running_tasks_key = 'blockchain_running_tasks'

    def __init__(self):
        self.redis = get_redis()

    def stop_running_tasks(self):
        tasks_to_kill = self.get_running_tasks()
        if tasks_to_kill:
            logger.warning('Stopping running tasks. Sending SIGTERM to task_ids=%s', tasks_to_kill)
            celery_app.control.revoke(tasks_to_kill, terminate=True, signal=signal.SIGTERM)
            self.delete_all_tasks()
        return tasks_to_kill

    def get_running_tasks(self) -> List[str]:
        return [task_id.decode() for task_id in self.redis.lrange(self.blockchain_running_tasks_key, 0, -1)]

    def add_task(self, task_id: str):
        return self.redis.lpush(self.blockchain_running_tasks_key, task_id)

    def remove_task(self, task_id: str):
        return self.redis.lrem(self.blockchain_running_tasks_key, 0, task_id)

    def delete_all_tasks(self):
        return self.redis.delete(self.blockchain_running_tasks_key)


class BlockchainRunningTask:
    """
    Context Manager to store blockchain related task ids. That way we can terminate all blockchain related tasks at
    once, e.g. reorg is detected
    """
    def __init__(self, celery_context: CeleryContext):
        self.blockchain_running_task_manager = BlockchainRunningTaskManager()
        self.celery_request = celery_context
        self.task_id: str = celery_context.id

    def __enter__(self):
        signal.signal(signal.SIGTERM, generate_handler(self.task_id))
        self.blockchain_running_task_manager.add_task(self.task_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.blockchain_running_task_manager.remove_task(self.task_id)
        close_gevent_db_connection()  # Need for django-db-geventpool


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT)
def index_new_proxies_task(self) -> Optional[int]:
    """
    :return: Number of proxies created
    """
    with contextlib.suppress(LockError):
        with ony_one_running_task(self):
            with BlockchainRunningTask(self.request):
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
            with BlockchainRunningTask(self.request):
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
            with BlockchainRunningTask(self.request):
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
    finally:
        close_gevent_db_connection()


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
                internal_txs_decoded = InternalTxDecoded.objects.pending_for_safe(safe_address)[:batch]
                if not internal_txs_decoded:
                    break
                number_processed += len(tx_processor.process_decoded_transactions(internal_txs_decoded))
                logger.info('Processed %d decoded transactions', number_processed)
            if number_processed:
                logger.info('%d decoded internal txs successfully processed for safe %s',
                            number_processed, safe_address)
                return number_processed
    except LockError:
        pass
    finally:
        close_gevent_db_connection()


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
                # Stop running tasks
                BlockchainRunningTaskManager().stop_running_tasks()
                reorg_service.recover_from_reorg(first_reorg_block_number)
                return first_reorg_block_number
    except LockError:
        pass
    finally:
        close_gevent_db_connection()


@app.shared_task()
def send_webhook_task(address: Optional[str], payload: Dict[str, Any]) -> int:
    if not (address and payload):
        return 0

    try:
        webhooks = WebHook.objects.matching_for_address(address)
        if not webhooks:
            return 0

        sent_requests = 0
        for webhook in webhooks:
            webhook_type = WebHookType[payload['type']]
            if webhook_type == WebHookType.NEW_CONFIRMATION and not webhook.new_confirmation:
                continue
            elif webhook_type == WebHookType.PENDING_MULTISIG_TRANSACTION and not webhook.pending_outgoing_transaction:
                continue
            elif (webhook_type == WebHookType.EXECUTED_MULTISIG_TRANSACTION and not
                  webhook.new_executed_outgoing_transaction):
                continue
            elif webhook_type in (WebHookType.INCOMING_TOKEN,
                                  WebHookType.INCOMING_ETHER) and not webhook.new_incoming_transaction:
                continue

            parsed_url = urlparse(webhook.url)
            host = f'{parsed_url.scheme}://{parsed_url.netloc}'
            if webhook.address:
                logger.info('Sending webhook for address=%s host=%s and payload=%s', address, host, payload)
            else:  # Generic WebHook
                logger.info('Sending webhook for host=%s and payload=%s', host, payload)

            r = requests.post(webhook.url, json=payload)
            if not r.ok:
                logger.warning('Error %d posting to host=%s with content=%s', r.status_code, host, r.content)

            sent_requests += 1
        return sent_requests
    finally:
        close_gevent_db_connection()
