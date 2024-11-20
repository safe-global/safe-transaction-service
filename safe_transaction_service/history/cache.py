import json
from functools import cached_property, wraps
from typing import List, Optional, Union
from urllib.parse import urlencode

from django.conf import settings

from eth_typing import ChecksumAddress
from rest_framework import status
from rest_framework.response import Response

from safe_transaction_service.history.models import (
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    TokenTransfer,
)
from safe_transaction_service.utils.redis import get_redis, logger


class CacheSafeTxsView:
    """
    A generic caching class for managing cached responses from transactions endpoints.
    """

    # Cache tags
    LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY = "multisigtransactionsview"
    LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY = "moduletransactionsview"
    LIST_TRANSFERS_VIEW_CACHE_KEY = "transfersview"

    def __init__(self, cache_tag: str, address: ChecksumAddress):
        self.redis = get_redis()
        self.address = address
        self.cache_tag = cache_tag

    @cached_property
    def cache_name(self) -> str:
        """
        Calculate the cache_name from the cache_tag and address

        :param cache_tag:
        :param address:
        :return:
        """
        return f"{self.cache_tag}:{self.address}"

    @cached_property
    def enabled(self) -> bool:
        """

        :return: True if cache is enabled False otherwise
        """
        return bool(settings.CACHE_VIEW_DEFAULT_TIMEOUT)

    def get_cache_data(self, cache_path: str) -> Optional[str]:
        """
        Return the cache for the provided cache_path

        :param cache_path:
        :return:
        """
        if self.enabled:
            logger.debug(f"Getting from cache {self.cache_name}{cache_path}")
            return self.redis.hget(self.cache_name, cache_path)
        else:
            return None

    def set_cache_data(self, cache_path: str, data: str, timeout: int):
        """
        Set a cache for provided data with the provided timeout

        :param cache_path:
        :param data:
        :param timeout:
        :return:
        """
        if self.enabled:
            logger.debug(
                f"Setting cache {self.cache_name}{cache_path} with TTL {timeout} seconds"
            )
            self.redis.hset(self.cache_name, cache_path, data)
            self.redis.expire(self.cache_name, timeout)
        else:
            logger.warning("Cache txs view is disabled")

    def remove_cache(self):
        """
        Remove cache key stored in redis for the provided parameters

        :param cache_name:
        :return:
        """
        logger.debug(f"Removing all the cache for {self.cache_name}")
        self.redis.unlink(self.cache_name)


def cache_txs_view_for_address(
    cache_tag: str,
    parameter_key: str = "address",
    timeout: int = settings.CACHE_VIEW_DEFAULT_TIMEOUT,
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
            # Get sorted query parameters
            query_params = sorted(request.request.GET.dict().items())
            cache_path = urlencode(query_params)
            # Calculate cache_name
            address = request.kwargs.get(parameter_key)
            cache_txs_view: Optional[CacheSafeTxsView] = None
            if address:
                cache_txs_view = CacheSafeTxsView(cache_tag, address)
            else:
                logger.warning(
                    "Address does not exist in the request, this will not be cached"
                )
                cache_txs_view = None

            if cache_txs_view:
                # Check if response is cached
                response_data = cache_txs_view.get_cache_data(cache_path)
                if response_data:
                    return Response(
                        status=status.HTTP_200_OK, data=json.loads(response_data)
                    )

            # Get response from the view
            response = view_func(request, *args, **kwargs)
            if response.status_code == 200:
                # Just store success responses and if cache is enabled with DEFAULT_CACHE_PAGE_TIMEOUT > 0
                if cache_txs_view:
                    cache_txs_view.set_cache_data(
                        cache_path, json.dumps(response.data), timeout
                    )

            return response

        return _wrapped_view

    return decorator


def remove_cache_view_by_instance(
    instance: Union[
        TokenTransfer,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        ModuleTransaction,
    ]
):
    """
    Remove the cache stored for instance view.

    :param instance:
    """
    addresses = []
    cache_tag: Optional[str] = None
    if isinstance(instance, TokenTransfer):
        cache_tag = CacheSafeTxsView.LIST_TRANSFERS_VIEW_CACHE_KEY
        addresses.append(instance.to)
        addresses.append(instance._from)
    elif isinstance(instance, MultisigTransaction):
        cache_tag = CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.safe)
    elif isinstance(instance, MultisigConfirmation) and instance.multisig_transaction:
        cache_tag = CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.multisig_transaction.safe)
    elif isinstance(instance, InternalTx):
        cache_tag = CacheSafeTxsView.LIST_TRANSFERS_VIEW_CACHE_KEY
        addresses.append(instance.to)
        if instance._from:
            addresses.append(instance._from)
    elif isinstance(instance, ModuleTransaction):
        cache_tag = CacheSafeTxsView.LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY
        addresses.append(instance.safe)

    if cache_tag:
        remove_cache_view_for_addresses(cache_tag, addresses)


def remove_cache_view_for_addresses(cache_tag: str, addresses: List[ChecksumAddress]):
    """
    Remove several cache for the provided cache_tag and addresses

    :param cache_tag:
    :param addresses:
    :return:
    """
    for address in addresses:
        cache_safe_txs = CacheSafeTxsView(cache_tag, address)
        cache_safe_txs.remove_cache()
