
from typing import Optional

from django.conf import settings

from celery import app
from celery.utils.log import get_task_logger

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork

from safe_transaction_service.history.utils import (close_gevent_db_connection,
                                                    get_redis)

from .models import Token
from .services.price_service import PriceServiceProvider

logger = get_task_logger(__name__)


@app.shared_task()
def fix_pool_tokens_task() -> Optional[int]:
    """
    Fix names for generic pool tokens, like Balancer or Uniswap
    :return: Number of pool token names updated
    """
    ethereum_client = EthereumClientProvider()
    ethereum_network = ethereum_client.get_network()
    if ethereum_network == EthereumNetwork.MAINNET:
        try:
            number = Token.pool_tokens.fix_all_pool_tokens()
            if number:
                logger.info('%d pool token names were fixed', number)
            return number
        finally:
            close_gevent_db_connection()


@app.shared_task()
def calculate_token_eth_price(token_address: str, redis_key: str) -> Optional[float]:
    """
    Do price calculation for token in an async way and store it on redis
    :param token_address: Token address
    :param redis_key: Redis key for token price
    :return: token price (in ether) when calculated
    """
    redis = get_redis()
    price_service = PriceServiceProvider()
    eth_price = price_service.get_token_eth_value(token_address)
    if not eth_price:  # Try usd oracles
        usd_price = price_service.get_token_usd_price(token_address)
        if usd_price:
            eth_usd_price = price_service.get_eth_usd_price()
            eth_price = usd_price / eth_usd_price
    redis_expiration_time = 60 * 30  # Expire in 30 minutes
    redis.setex(redis_key, redis_expiration_time, eth_price)
    if eth_price and not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
        # Recalculate price before cache expires and prevents recursion checking Celery Eager property
        calculate_token_eth_price.apply_async((token_address, redis_key), countdown=redis_expiration_time - 300)
    return eth_price
