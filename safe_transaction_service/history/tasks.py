import signal
from typing import Any, Dict, List, NoReturn, Optional

from django.conf import settings

import requests
from celery import app
from celery.signals import worker_shutting_down
from celery.utils.log import get_task_logger
from celery.worker.request import Request as CeleryRequest
from redis import Redis
from redis.exceptions import LockError

from ..taskapp.celery import app as celery_app
from .indexers import (Erc20EventsIndexerProvider, InternalTxIndexerProvider,
                       ProxyFactoryIndexerProvider)
from .indexers.tx_processor import SafeTxProcessor, TxProcessor
from .models import InternalTxDecoded, WebHook, WebHookType
from .services import ReorgService, ReorgServiceProvider

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 10  # 10 minutes


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


def generate_handler(task_id: str) -> NoReturn:
    def handler(signum, frame):
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
    Context Manager to store blockchain related task ids. That way we can terminate all blockchain related task at
    once, e.g. reorg is detected
    """
    def __init__(self, celery_request: CeleryRequest):
        self.blockchain_running_task_manager = BlockchainRunningTaskManager()
        self.celery_request = celery_request
        self.task_id: str = celery_request.id

    def __enter__(self):
        signal.signal(signal.SIGTERM, generate_handler(self.task_id))
        self.blockchain_running_task_manager.add_task(self.task_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.blockchain_running_task_manager.remove_task(self.task_id)


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning('Worker shutting down')
    return len(BlockchainRunningTaskManager().stop_running_tasks())


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_new_proxies_task(self) -> Optional[int]:
    """
    :return: Number of proxies created
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            with BlockchainRunningTask(self.request):
                logger.info('Start indexing of new proxies')
                number_proxies = ProxyFactoryIndexerProvider().start()
                if number_proxies:
                    logger.info('Indexed new %d proxies', number_proxies)
                    return number_proxies
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_internal_txs_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            with BlockchainRunningTask(self.request):
                logger.info('Start indexing of internal txs')
                number_traces = InternalTxIndexerProvider().start()
                logger.info('Find internal txs task processed %d traces', number_traces)
                if number_traces:
                    logger.info('Calling task to process decoded traces')
                    process_decoded_internal_txs_task.delay()
                return number_traces
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_erc20_events_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_erc20_events_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            with BlockchainRunningTask(self.request):
                logger.info('Start indexing of erc20/721 events')
                number_events = Erc20EventsIndexerProvider().start()
                logger.info('Indexing of erc20/721 events task processed %d events', number_events)
                return number_events
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task() -> Optional[int]:
    redis = get_redis()
    try:
        with redis.lock('tasks:process_decoded_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            logger.info('Start processing decoded internal txs')
            number_processed = 0
            count = InternalTxDecoded.objects.not_processed().count()  # Just get a rough estimate, faster for DB
            batch = 500
            if not count:
                logger.info('No decoded internal txs to process')
            else:
                logger.info('%d as much decoded internal txs to process. Starting with first %d', count, min(batch,
                                                                                                             count))
                tx_processor: TxProcessor = SafeTxProcessor()
                # Use slicing for memory issues
                for _ in range(0, count, batch):
                    internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()[:batch]
                    if not internal_txs_decoded:
                        break
                    number_processed += len(tx_processor.process_decoded_transactions(internal_txs_decoded))
                    logger.info('Processed %d/%d decoded transactions', number_processed, count)
            if number_processed:
                logger.info('%d decoded internal txs successfully processed', number_processed)
                return number_processed
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def check_reorgs_task() -> Optional[int]:
    """
    :return: Number of oldest block with reorg detected. `None` if not reorg found
    """
    redis = get_redis()
    try:
        with redis.lock('tasks:check_reorgs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
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


@app.shared_task()
def send_webhook_task(address: Optional[str], payload: Dict[str, Any]) -> int:
    if not (address and payload):
        return 0

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

        if webhook.address:
            logger.info('Sending webhook for address=%s url=%s and payload=%s', address, webhook.url, payload)
        else:  # Generic WebHook
            logger.info('Sending webhook for url=%s and payload=%s', webhook.url, payload)

        r = requests.post(webhook.url, json=payload)
        if not r.ok:
            logger.warning('Error posting to url=%s', webhook.url)

        sent_requests += 1
    return sent_requests
