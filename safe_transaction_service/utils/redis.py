import copyreg
import logging
import pickle
from functools import cache, wraps
from urllib.parse import urlencode

from django.conf import settings

from redis import Redis

logger = logging.getLogger(__name__)


@cache
def get_redis() -> Redis:
    logger.info("Opening connection to Redis")

    # Encode memoryview for redis when using pickle
    copyreg.pickle(memoryview, lambda val: (memoryview, (bytes(val),)))

    return Redis.from_url(settings.REDIS_URL)


def cache_view_response(timeout: int, cache_name: str):
    """
    Custom cache decorator that caches the view response.
    This decorator caches the response of a view function for a specified timeout.
    It allows you to cache the response based on a unique cache name, which can
    be used for invalidating.

    :param timeout: Cache timeout in seconds.
    :param cache_name: A unique identifier for the cache entry.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            redis = get_redis()
            # Get query parameters
            query_params = request.GET.dict()
            cache_path = f"{request.path}:{urlencode(query_params)}"

            # Check if response is cached
            response = redis.hget(cache_name, cache_path)
            if response:
                return pickle.loads(response)

            # Get response from the view
            response = view_func(request, *args, **kwargs).render()
            if response.status_code == 200:
                # We just store the success result
                redis.hset(cache_name, cache_path, pickle.dumps(response))
                redis.expire(cache_name, timeout)

            return response

        return _wrapped_view

    return decorator


def remove_cache_view_response(cache_name: str):
    """
    Remove cache key stored in redis

    :param cache_name:
    :return:
    """
    get_redis().unlink(cache_name)
