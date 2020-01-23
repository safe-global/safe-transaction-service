import signal
from typing import Any, Dict, NoReturn, Optional, Type, Union

from django.conf import settings
from django.db.models import Model

import requests
from celery import app
from celery.signals import worker_shutting_down
from celery.utils.log import get_task_logger
from redis import Redis
from redis.exceptions import LockError

from gnosis.eth import EthereumClientProvider

from ..taskapp.celery import app as celery_app
from .indexers import (Erc20EventsIndexerProvider, InternalTxIndexerProvider,
                       ProxyIndexerServiceProvider)
from .indexers.tx_processor import SafeTxProcessor, TxProcessor
from .models import (InternalTxDecoded, MultisigConfirmation,
                     MultisigTransaction, WebHook, WebHookType)
from .services import ReorgService, ReorgServiceProvider

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 10  # 10 minutes

blockchain_running_tasks_key = 'blockchain_running_tasks'


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


def generate_handler(task_id: str) -> NoReturn:
    def handler(signum, frame):
        logger.warning('Received SIGTERM on task-id=%s', task_id)
        raise OSError('Received SIGTERM on task-id=%s. Probably a reorg. Task must exit' % task_id)
    return handler


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning('Worker shutting down')
    tasks_to_kill = [task_id.decode() for task_id in get_redis().lrange(blockchain_running_tasks_key, 0, -1)]
    # Not working, as the worker cannot answer anymore
    if tasks_to_kill:
        logger.warning('Sending SIGTERM to task_ids=%s', tasks_to_kill)
        celery_app.control.revoke(tasks_to_kill, terminate=True, signal=signal.SIGTERM)
        get_redis().delete(blockchain_running_tasks_key)


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_new_proxies_task(self) -> Optional[int]:
    """
    :return: Number of proxies created
    """

    redis = get_redis()
    got_lock = True
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            task_id = self.request.id
            signal.signal(signal.SIGTERM, generate_handler(task_id))
            redis.lpush(blockchain_running_tasks_key, task_id)
            number_proxies = ProxyIndexerServiceProvider().start()
            if number_proxies:
                logger.info('Indexed new %d proxies', number_proxies)
                return number_proxies
    except LockError:
        got_lock = False
    finally:
        if got_lock:
            redis.lrem(blockchain_running_tasks_key, 0, task_id)


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_internal_txs_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    got_lock = True
    try:
        with redis.lock('tasks:index_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            task_id = self.request.id
            signal.signal(signal.SIGTERM, generate_handler(task_id))
            logger.info('Start indexing of internal txs')
            redis.lpush(blockchain_running_tasks_key, task_id)
            number_traces = InternalTxIndexerProvider().start()
            logger.info('Find internal txs task processed %d traces', number_traces)
            process_decoded_internal_txs_task.delay()
            return number_traces
    except LockError:
        got_lock = False
    finally:
        if got_lock:
            redis.lrem(blockchain_running_tasks_key, 0, task_id)


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT)
def index_erc20_events_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    got_lock = True
    try:
        with redis.lock('tasks:index_erc20_events_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            task_id = self.request.id
            signal.signal(signal.SIGTERM, generate_handler(task_id))
            logger.info('Start indexing of erc20/721 events')
            redis.lpush(blockchain_running_tasks_key, task_id)
            number_events = Erc20EventsIndexerProvider().start()
            logger.info('Indexing of erc20/721 events task processed %d events', number_events)
            return number_events
    except LockError:
        got_lock = False
    finally:
        if got_lock:
            redis.lrem(blockchain_running_tasks_key, 0, task_id)


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task() -> Optional[int]:
    redis = get_redis()
    try:
        with redis.lock('tasks:process_decoded_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            number_processed = 0
            count = InternalTxDecoded.objects.pending_for_safes().count()
            batch = 150
            if count:
                tx_processor: TxProcessor = SafeTxProcessor(EthereumClientProvider())
                logger.info('%d decoded internal txs to process. Starting with first %d', count, min(batch, count))
                # Use slicing for memory issues
                for _ in range(0, count, batch):
                    for internal_tx_decoded in InternalTxDecoded.objects.pending_for_safes()[:batch]:
                        processed = tx_processor.process_decoded_transaction(internal_tx_decoded)
                        if processed:
                            number_processed += 1
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
        with redis.lock('tasks:check_reorgs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT) as redis_lock:
            reorg_service: ReorgService = ReorgServiceProvider()
            first_reorg_block_number = reorg_service.check_reorgs()
            if first_reorg_block_number:
                # Stop running tasks
                celery_app.control.revoke([task_id.decode()  # Redis returns `bytes`
                                           for task_id in redis.lrange(blockchain_running_tasks_key, 0, -1)],
                                          terminate=True, signal=signal.SIGTERM)
                redis.delete(blockchain_running_tasks_key)
                reorg_service.recover_from_reorg(first_reorg_block_number)
                return first_reorg_block_number
    except LockError:
        pass


@app.shared_task()
def send_webhook_task(address: Optional[str], payload: Dict[str, Any]) -> bool:
    if not (address and payload):
        return False

    try:
        webhook = WebHook.objects.get(address=address)
    except WebHook.DoesNotExist:
        return False

    webhook_type = WebHookType[payload['type']]
    if webhook_type == WebHookType.NEW_CONFIRMATION and not webhook.new_confirmation:
        return False
    elif webhook_type == WebHookType.PENDING_MULTISIG_TRANSACTION and not webhook.pending_outgoing_transaction:
        return False
    elif webhook_type == WebHookType.EXECUTED_MULTISIG_TRANSACTION and not webhook.new_executed_outgoing_transaction:
        return False
    elif webhook_type in (WebHookType.INCOMING_TOKEN,
                          WebHookType.INCOMING_ETHER) and not webhook.new_incoming_transaction:
        return False

    logger.info('Sending webhook for address=%s url=%s and payload=%s', address, webhook.url, payload)
    requests.post(webhook.url, json=payload)
