import signal
from typing import Optional, List, NoReturn

from celery.signals import worker_shutting_down, worker_ready, worker_process_init
from celery.worker.control import revoke
from celery.worker.request import Request
from django.conf import settings

from celery import app
from celery.utils.log import get_task_logger
from gnosis.eth import EthereumClientProvider
from hexbytes import HexBytes
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock

from .indexers import InternalTxIndexerProvider, ProxyIndexerServiceProvider
from .indexers.tx_processor import TxProcessor
from .models import InternalTxDecoded, EthereumBlock, MonitoredAddress
from ..taskapp.celery import app as celery_app

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 10  # 10 minutes

blockchain_running_tasks_key = 'blockchain_running_tasks'


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


def release_lock(request: Request, redis_lock: Lock) -> NoReturn:
    def fn(signum, frame):
        get_redis().lrem(blockchain_running_tasks_key, 0, request.id)
        redis_lock.release()
        logger.warning(f'Received SIGTERM on task %s', request.name)
    return fn


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    tasks_to_kill = [task_id.decode() for task_id in get_redis().lrange(blockchain_running_tasks_key, 0, -1)]
    if tasks_to_kill:
        get_redis().delete(blockchain_running_tasks_key)
        logger.warning('Sending SIGTERM to task_ids=%s', tasks_to_kill)
        celery_app.control.revoke(tasks_to_kill, terminate=True, signal=signal.SIGTERM)


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_new_proxies_task() -> Optional[int]:
    """
    :return: Number of proxies created
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT) as redis_lock:
            signal.signal(signal.SIGTERM, release_lock(index_new_proxies_task.request, redis_lock))
            redis.lpush(blockchain_running_tasks_key, index_new_proxies_task.request.id)
            proxy_factory_addresses = ['0x12302fE9c02ff50939BaAaaf415fc226C078613C']
            proxy_indexer_service = ProxyIndexerServiceProvider()

            new_monitored_addresses = 0
            updated = False

            while not updated:
                created_objects, updated = proxy_indexer_service.process_addresses(proxy_factory_addresses)
                new_monitored_addresses += len(created_objects)

            redis.lrem(blockchain_running_tasks_key, 0, index_new_proxies_task.request.id)
            if new_monitored_addresses:
                logger.info('Indexed new %d proxies', new_monitored_addresses)
                return new_monitored_addresses
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_internal_txs_task() -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT) as redis_lock:
            signal.signal(signal.SIGTERM, release_lock(index_internal_txs_task.request, redis_lock))
            redis.lpush(blockchain_running_tasks_key, index_internal_txs_task.request.id)
            number_addresses = InternalTxIndexerProvider().process_all()
            redis.lrem(blockchain_running_tasks_key, 0, index_internal_txs_task.request.id)
            if number_addresses:
                logger.info('Find internal txs task processed %d addresses', number_addresses)
                return number_addresses
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task() -> Optional[int]:
    redis = get_redis()
    try:
        with redis.lock('tasks:process_decoded_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            tx_processor = TxProcessor()
            number_processed = 0
            for internal_tx_decoded in InternalTxDecoded.objects.pending():
                processed = tx_processor.process_decoded_transaction(internal_tx_decoded)
                if processed:
                    number_processed += 1
            if number_processed:
                logger.info('%d decoded internal txs processed', number_processed)
                return number_processed
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def check_reorgs_task() -> Optional[int]:
    redis = get_redis()
    try:
        with redis.lock('tasks:check_reorgs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT) as redis_lock:
            signal.signal(signal.SIGTERM, release_lock(check_reorgs_task.request, redis_lock))
            #TODO Fetch multiple block hashes at once
            ethereum_client = EthereumClientProvider()
            current_block_number = ethereum_client.current_block_number
            block_reorgs: List[int] = []
            for database_block in EthereumBlock.objects.not_confirmed():
                blockchain_block = ethereum_client.get_block(database_block.number, full_transactions=False)
                if HexBytes(blockchain_block['hash']) != HexBytes(database_block.block_hash):
                    logger.warning('Reorg found for block number=%d', database_block.number)
                    block_reorgs.append(database_block.number)
                else:
                    if (current_block_number - database_block.number) > 6:
                        database_block.set_confirmed()

            if block_reorgs:
                revoke([str(task_id) for task_id in redis.lrange(blockchain_running_tasks_key, 0, -1)], terminate=True)

                min_block = min(block_reorgs)
                EthereumBlock.objects.filter(number__gte=min_block).delete()
                # Check concurrency problems
                MonitoredAddress.objects.filter(tx_block_number__gte=min_block).update(tx_block_number=min_block - 1)
                logger.info('%d reorgs fixed', len(block_reorgs))
                return len(block_reorgs)
    except LockError:
        pass
