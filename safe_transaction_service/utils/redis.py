import copyreg
import logging
from functools import cache

from django.conf import settings

from redis import ConnectionPool, Redis

logger = logging.getLogger(__name__)


@cache
def get_redis() -> Redis:
    logger.info("Opening connection to Redis")

    # Encode memoryview for redis when using pickle
    copyreg.pickle(memoryview, lambda val: (memoryview, (bytes(val),)))

    connection_pool = ConnectionPool(
        max_connections=settings.REDIS_POOL_MAX_CONNECTIONS
    ).from_url(
        settings.REDIS_URL,
        socket_connect_timeout=settings.REDIS_CONNECTION_TIMEOUT_SECONDS,
        socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        health_check_interval=30,
    )
    return Redis(connection_pool=connection_pool)
