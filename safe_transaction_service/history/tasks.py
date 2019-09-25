import signal
from typing import List, NoReturn, Optional

from django.conf import settings

from celery import app
from celery.app.task import Context
from celery.signals import worker_shutting_down
from celery.utils.log import get_task_logger
from hexbytes import HexBytes
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock

from gnosis.eth import EthereumClientProvider

from ..taskapp.celery import app as celery_app
from .indexers import InternalTxIndexerProvider, ProxyIndexerServiceProvider
from .indexers.tx_processor import TxProcessor
from .models import EthereumBlock, InternalTxDecoded, MonitoredAddress, ProxyFactory

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
        raise OSError('Task must exit')
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
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            task_id = self.request.id
            signal.signal(signal.SIGTERM, generate_handler(task_id))
            redis.lpush(blockchain_running_tasks_key, task_id)
            proxy_factory_addresses = ['0x12302fE9c02ff50939BaAaaf415fc226C078613C']
            proxy_indexer_service = ProxyIndexerServiceProvider()

            new_monitored_addresses = 0
            updated = False

            while not updated:
                created_objects, updated = proxy_indexer_service.process_addresses(proxy_factory_addresses)
                new_monitored_addresses += len(created_objects)

            redis.lrem(blockchain_running_tasks_key, 0, task_id)
            if new_monitored_addresses:
                logger.info('Indexed new %d proxies', new_monitored_addresses)
                return new_monitored_addresses
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
            task_id = self.request.id
            signal.signal(signal.SIGTERM, generate_handler(task_id))
            redis.lpush(blockchain_running_tasks_key, task_id)
            logger.info('Start indexing of internal txs')
            number_addresses = InternalTxIndexerProvider().process_all()
            redis.lrem(blockchain_running_tasks_key, 0, task_id)
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


def check_reorgs() -> Optional[int]:
    """
    :return: Number of oldest block with reorg detected. `None` if not reorg found
    """
    ethereum_client = EthereumClientProvider()
    current_block_number = ethereum_client.current_block_number
    first_reorg_block_number: Optional[int] = None
    for database_block in EthereumBlock.objects.not_confirmed():
        blockchain_block = ethereum_client.get_block(database_block.number, full_transactions=False)
        if HexBytes(blockchain_block['hash']) != HexBytes(database_block.block_hash):
            logger.warning('Reorg found for block-number=%d', database_block.number)
            first_reorg_block_number = database_block.number
            break
        else:
            database_block.set_confirmed(current_block_number)

    if first_reorg_block_number is not None:
        # Check concurrency problems
        EthereumBlock.objects.filter(number__gte=first_reorg_block_number).delete()

        ProxyFactory.objects.filter(
            index_block_number__gte=first_reorg_block_number
        ).update(
            index_block_number=first_reorg_block_number - 1
        )

        MonitoredAddress.objects.filter(
            tx_block_number__gte=first_reorg_block_number
        ).reset_block_number(
            block_number=first_reorg_block_number - 1
        )

        logger.info('Reorg of block-number=%d fixed', first_reorg_block_number)
    return first_reorg_block_number


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def check_reorgs_task() -> Optional[int]:
    """
    :return: Number of oldest block with reorg detected. `None` if not reorg found
    """
    redis = get_redis()
    try:
        with redis.lock('tasks:check_reorgs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT) as redis_lock:
            first_reorg_block_number = check_reorgs()
            if first_reorg_block_number:
                celery_app.control.revoke([task_id.decode()  # Redis returns `bytes`
                                           for task_id in redis.lrange(blockchain_running_tasks_key, 0, -1)],
                                          terminate=True, signal=signal.SIGTERM)
                redis.delete(blockchain_running_tasks_key)
                return first_reorg_block_number
    except LockError:
        pass
