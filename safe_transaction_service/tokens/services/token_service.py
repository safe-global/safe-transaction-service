# SPDX-License-Identifier: FSL-1.1-MIT
from threading import Lock

from django.conf import settings

from cachetools import TTLCache
from eth_typing import ChecksumAddress

from ..models import Token


class TokenServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = TokenService()
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TokenService:
    def __init__(self):
        self.cache_trusted_addresses: TTLCache[str, frozenset[ChecksumAddress]] = (
            TTLCache(maxsize=1, ttl=settings.TOKENS_TRUSTED_CACHE_TTL)
        )
        self._trusted_addresses_lock = Lock()

    def _load_trusted_token_addresses(self) -> frozenset[ChecksumAddress]:
        return frozenset(
            Token.objects.filter(trusted=True).values_list("address", flat=True)
        )

    def get_trusted_token_addresses(self) -> frozenset[ChecksumAddress]:
        """
        :return: Set with the addresses of every trusted token. Cached in memory
            for ``TOKENS_TRUSTED_CACHE_TTL`` seconds.
        """
        cache_key = "trusted_addresses"
        try:
            return self.cache_trusted_addresses[cache_key]
        except KeyError:
            pass

        # Lock to avoid a stampede of concurrent queries refilling the cache
        with self._trusted_addresses_lock:
            try:
                return self.cache_trusted_addresses[cache_key]
            except KeyError:
                trusted_addresses = self._load_trusted_token_addresses()
                self.cache_trusted_addresses[cache_key] = trusted_addresses
                return trusted_addresses

    def is_trusted(self, token_address: ChecksumAddress) -> bool:
        """
        :param token_address:
        :return: ``True`` if the token is trusted, ``False`` otherwise
        """
        return token_address in self.get_trusted_token_addresses()
