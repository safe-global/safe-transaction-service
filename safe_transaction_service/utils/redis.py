from functools import cache

from django.conf import settings

from redis import Redis


@cache
def get_redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL)
