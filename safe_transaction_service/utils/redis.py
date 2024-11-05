import copyreg
import json
import logging
from functools import cache, wraps
from typing import List, Optional, Union
from urllib.parse import urlencode

from django.conf import settings

from eth_typing import ChecksumAddress
from redis import Redis
from rest_framework import status
from rest_framework.response import Response

from safe_transaction_service.contracts.models import Contract
from safe_transaction_service.history.models import (
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    TokenTransfer,
)

logger = logging.getLogger(__name__)


@cache
def get_redis() -> Redis:
    logger.info("Opening connection to Redis")

    # Encode memoryview for redis when using pickle
    copyreg.pickle(memoryview, lambda val: (memoryview, (bytes(val),)))

    return Redis.from_url(settings.REDIS_URL)


LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY = "multisigtransactionsview"
LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY = "moduletransactionsview"
LIST_TRANSFERS_VIEW_CACHE_KEY = "transfersview"


def get_cache_page_name(cache_tag: str, address: ChecksumAddress) -> str:
    """
    Calculate the cache_name from the cache_tag and provided address

    :param cache_tag:
    :param address:
    :return:
    """
    return f"{cache_tag}:{address}"


def cache_page_for_address(
    cache_tag: str, timeout: int = settings.DEFAULT_CACHE_PAGE_TIMEOUT
):
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
            query_params = request.request.GET.dict()
            cache_path = f"{urlencode(query_params)}"
            # Calculate cache_name
            address = request.kwargs["address"]
            if address:
                cache_name = get_cache_page_name(cache_tag, address)
            else:
                logger.warning(
                    "Address does not exist in the request, this will not be cached"
                )
                cache_name = None

            if cache_name:
                # Check if response is cached
                response_data = redis.hget(cache_name, cache_path)
                if response_data:
                    logger.debug(f"Getting from cache {cache_name}{cache_path}")
                    return Response(
                        status=status.HTTP_200_OK, data=json.loads(response_data)
                    )

            # Get response from the view
            response = view_func(request, *args, **kwargs)
            if response.status_code == 200:
                # Just store if there were not issues calculating cache_name
                if cache_name:
                    # We just store the success result
                    logger.debug(
                        f"Setting cache {cache_name}{cache_path} with TTL {timeout} seconds"
                    )
                    redis.hset(cache_name, cache_path, json.dumps(response.data))
                    redis.expire(cache_name, timeout)

            return response

        return _wrapped_view

    return decorator


def remove_cache_page_by_address(cache_tag: str, address: ChecksumAddress):
    """
    Remove cache key stored in redis for the provided parameters

    :param cache_name:
    :return:
    """
    cache_name = get_cache_page_name(cache_tag, address)

    logger.debug(f"Removing all the cache for {cache_name}")
    get_redis().unlink(cache_name)


def remove_cache_page_for_addresses(cache_tag: str, addresses: List[ChecksumAddress]):
    """
    Remove cache for provided addresses

    :param cache_tag:
    :param addresses:
    :return:
    """
    for address in addresses:
        remove_cache_page_by_address(cache_tag, address)


def remove_cache_view_by_instance(
    instance: Union[
        TokenTransfer,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        ModuleTransaction,
        Contract,
    ]
):
    """
    Remove the cache stored for instance view.

    :param instance:
    """
    addresses = []
    cache_tag: Optional[str] = None
    if isinstance(instance, TokenTransfer):
        cache_tag = LIST_TRANSFERS_VIEW_CACHE_KEY
        addresses.append(instance.to)
        addresses.append(instance._from)
    elif isinstance(instance, MultisigTransaction):
        cache_tag = LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.safe)
    elif isinstance(instance, MultisigConfirmation) and instance.multisig_transaction:
        cache_tag = LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.multisig_transaction.safe)
    elif isinstance(instance, InternalTx):
        cache_tag = LIST_TRANSFERS_VIEW_CACHE_KEY
        addresses.append(instance.to)
    elif isinstance(instance, ModuleTransaction):
        cache_tag = LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.safe)

    if cache_tag:
        remove_cache_page_for_addresses(cache_tag, addresses)
