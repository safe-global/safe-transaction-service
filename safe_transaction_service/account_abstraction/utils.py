import logging
from functools import cache
from typing import Optional

from django.conf import settings

from gnosis.eth.account_abstraction import BundlerClient

logger = logging.getLogger(__name__)


@cache
def get_bundler_client() -> Optional[BundlerClient]:
    """
    :return: Initialized `ERC4337 RPC Bundler Client` if configured, `None` otherwise
    """
    if settings.ETHEREUM_4337_BUNDLER_URL:
        return BundlerClient(settings.ETHEREUM_4337_BUNDLER_URL)
    logger.warning("ETHEREUM_4337_BUNDLER_URL not set, cannot configure bundler client")
    return None
