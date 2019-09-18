from django.conf import settings

from celery import app
from celery.utils.log import get_task_logger
from redis import Redis
from redis.exceptions import LockError

from .indexers import InternalTxIndexerProvider, ProxyIndexerServiceProvider
from .indexers.tx_processor import TxProcessor
from .models import InternalTxDecoded

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 10  # 10 minutes


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_new_proxies_task() -> int:
    """
    :return: Number of proxies created
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            proxy_factory_addresses = ['0x12302fE9c02ff50939BaAaaf415fc226C078613C']
            proxy_indexer_service = ProxyIndexerServiceProvider()

            new_monitored_addresses = 0
            updated = False

            while not updated:
                created_objects, updated = proxy_indexer_service.process_addresses(proxy_factory_addresses)
                new_monitored_addresses += len(created_objects)

            if new_monitored_addresses:
                logger.info('Indexed new %d proxies', new_monitored_addresses)

            return new_monitored_addresses
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_internal_txs_task() -> int:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            number_addresses = InternalTxIndexerProvider().process_all()
            logger.info('Find internal txs task processed %d addresses', number_addresses)
            return number_addresses
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task() -> int:
    redis = get_redis()
    try:
        with redis.lock('tasks:process_decoded_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            tx_processor = TxProcessor()
            number_processed = 0
            # It seems that it cannot manage many decoded objects, so we limit them
            for internal_tx_decoded in InternalTxDecoded.objects.pending()[:200]:
                processed = tx_processor.process_decoded_transaction(internal_tx_decoded)
                if processed:
                    number_processed += 1
                    internal_tx_decoded.set_processed()
            if number_processed:
                logger.info('%d decoded internal txs processed', number_processed)
            return number_processed
    except LockError:
        pass
