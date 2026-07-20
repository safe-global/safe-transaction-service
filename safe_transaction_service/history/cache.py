# SPDX-License-Identifier: FSL-1.1-MIT
import json
from collections.abc import Collection
from functools import cached_property, wraps
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction

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

    def get_cache_data(self, cache_path: str) -> str | None:
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
            cache_txs_view: CacheSafeTxsView | None = None
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


def get_cache_view_tag_and_addresses(
    instance: TokenTransfer
    | InternalTx
    | MultisigConfirmation
    | MultisigTransaction
    | ModuleTransaction,
) -> tuple[str, list[ChecksumAddress]] | None:
    """
    Resolve which view cache the instance invalidates.

    :param instance:
    :return: Tuple of cache tag and addresses whose cached views the instance
        invalidates, or ``None`` if the instance has no cached view
    """
    addresses = []
    cache_tag: str | None = None
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
        return cache_tag, addresses
    return None


def remove_cache_views(cache_names: Collection[str]) -> None:
    """
    Remove the provided cached views with a single Redis call. Never raises:
    it runs inside model signals, and a cache backend failure must not break
    the write that triggered it (entries expire by TTL anyway).

    :param cache_names: Cache keys as built by ``CacheSafeTxsView.cache_name``
    :return:
    """
    if not cache_names:
        return
    logger.debug("Removing all the cache for %s", cache_names)
    try:
        get_redis().unlink(*cache_names)
    except Exception:
        logger.warning("Could not remove the cache for %s", cache_names, exc_info=True)


def remove_cache_view_for_addresses(
    cache_tag: str, addresses: list[ChecksumAddress]
) -> None:
    """
    Remove the cached views for the provided cache_tag and addresses. With no
    transaction open the removal is immediate. Inside a transaction the cache
    only becomes wrong at commit — concurrent readers must keep seeing the
    pre-commit data it holds until then — so the keys are accumulated on the
    connection and removed together on commit with a single Redis call.

    :param cache_tag:
    :param addresses:
    :return:
    """
    cache_names = [f"{cache_tag}:{address}" for address in addresses]
    connection = transaction.get_connection()
    if not connection.in_atomic_block:
        remove_cache_views(cache_names)
    else:
        pending = connection.__dict__.get("_pending_cache_invalidations")
        if pending is None:
            pending = connection.__dict__["_pending_cache_invalidations"] = set()
        pending.update(cache_names)
        connection.on_commit(_remove_pending_cache_invalidations, robust=True)


def _remove_pending_cache_invalidations() -> None:
    """
    ``on_commit`` callback registered by ``remove_cache_view_for_addresses``
    for every cache-invalidating write of a transaction: the first one to run
    removes every cache key the transaction accumulated with a single Redis
    call, the rest find nothing to do. Keys left behind by a rolled-back
    transaction are drained by the next cache-invalidating commit on the
    connection — the cache can be invalidated in excess, never left stale.

    :return:
    """
    connection = transaction.get_connection()
    remove_cache_views(connection.__dict__.pop("_pending_cache_invalidations", ()))
