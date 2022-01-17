from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.conf import settings
from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress

from gnosis.eth.ethereum_client import EthereumNetwork

from safe_transaction_service.utils.ethereum import get_ethereum_network
from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from .models import Token

logger = get_task_logger(__name__)


@dataclass
class EthValueWithTimestamp(object):
    """
    Contains ethereum value for a token and the timestamp on when it was calculated
    """

    eth_value: float
    timestamp: datetime

    @classmethod
    def from_string(cls, result: str):
        eth_value, epoch = result.split(":")
        epoch_timestamp = datetime.fromtimestamp(float(epoch), timezone.utc)
        return cls(float(eth_value), epoch_timestamp)

    def __str__(self):
        return f"{self.eth_value}:{self.timestamp.timestamp()}"


@app.shared_task()
@close_gevent_db_connection_decorator
def calculate_token_eth_price_task(
    token_address: ChecksumAddress, redis_key: str, force_recalculation: bool = False
) -> Optional[EthValueWithTimestamp]:
    """
    Do price calculation for token in an async way and store it with its timestamp on redis

    :param token_address: Token address
    :param redis_key: Redis key for token price
    :param force_recalculation: Force a new calculation even if an old one is on cache
    :return: token price (in ether) when calculated
    """
    from .services.price_service import PriceServiceProvider

    redis_expiration_time = 60 * 30  # Expire in 30 minutes
    redis = get_redis()
    now = timezone.now()
    current_timestamp = int(now.timestamp())
    key_was_set = redis.set(
        redis_key, f"0:{current_timestamp}", ex=60 * 15, nx=True
    )  # Expire in 15 minutes
    if key_was_set or force_recalculation:
        price_service = PriceServiceProvider()
        eth_price = (
            price_service.get_token_eth_value(token_address)
            or price_service.get_token_usd_price(token_address)
            / price_service.get_native_coin_usd_price()
        )
        if not eth_price:  # Try composed oracles
            if underlying_tokens := price_service.get_underlying_tokens(token_address):
                eth_price = 0
                for underlying_token in underlying_tokens:
                    # Find underlying token price and multiply by quantity
                    address = underlying_token.address
                    eth_price += (
                        calculate_token_eth_price_task(
                            address,
                            f"price-service:{address}:eth-price",  # TODO Refactor all the calculation logic
                        ).eth_value
                        * underlying_token.quantity
                    )
        if eth_price:
            eth_value_with_timestamp = EthValueWithTimestamp(eth_price, now)
            redis.setex(redis_key, redis_expiration_time, str(eth_value_with_timestamp))
            if not getattr(settings, "CELERY_ALWAYS_EAGER", False):
                # Recalculate price before cache expires and prevents recursion checking Celery Eager property
                calculate_token_eth_price_task.apply_async(
                    (token_address, redis_key),
                    {"force_recalculation": True},
                    countdown=redis_expiration_time - 300,
                )
        else:
            logger.warning("Cannot calculate eth price for token=%s", token_address)
        return EthValueWithTimestamp(eth_price, now)
    else:
        return EthValueWithTimestamp.from_string(redis.get(redis_key).decode())


@app.shared_task()
@close_gevent_db_connection_decorator
def fix_pool_tokens_task() -> Optional[int]:
    """
    Fix names for generic pool tokens, like Balancer or Uniswap

    :return: Number of pool token names updated
    """
    if get_ethereum_network() == EthereumNetwork.MAINNET:
        number = Token.pool_tokens.fix_all_pool_tokens()
        if number:
            logger.info("%d pool token names were fixed", number)
        return number


@app.shared_task()
@close_gevent_db_connection_decorator
def get_token_info_from_blockchain_task(token_address: ChecksumAddress) -> bool:
    """
    Retrieve token information from blockchain

    :param token_address:
    :return: `True` if found, `False` otherwise
    """
    redis = get_redis()
    key = f"token-task:{token_address}"
    if result := redis.get(key):
        return bool(int(result))
    token_found = bool(Token.objects.create_from_blockchain(token_address))
    redis.setex(key, 60 * 60 * 6, int(token_found))  # Cache result 6 hours
    return token_found
