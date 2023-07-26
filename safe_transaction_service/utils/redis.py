import logging
from functools import cache

from django.conf import settings

from redis import Redis

logger = logging.getLogger(__name__)


@cache
def get_redis() -> Redis:
    logger.info("Opening connection to Redis")
    return Redis.from_url(settings.REDIS_URL)
