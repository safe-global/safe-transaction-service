from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress
from safe_eth.eth.ethereum_client import EthereumNetwork, get_auto_ethereum_client
from safe_eth.eth.utils import fast_to_checksum_address
from web3.exceptions import Web3Exception

from safe_transaction_service.utils.ethereum import get_ethereum_network
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from ..utils.celery import task_timeout
from .exceptions import TokenListRetrievalException
from .models import Token, TokenList, TokenListToken

logger = get_task_logger(__name__)

TASK_SOFT_TIME_LIMIT = 30  # 30 seconds
TASK_TIME_LIMIT = 60  # 1 minute


@dataclass
class EthValueWithTimestamp:
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
@task_timeout(timeout_seconds=TASK_TIME_LIMIT)
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


def _parse_token_address_from_token_list(
    token_address: str,
) -> Optional[ChecksumAddress]:
    if token_address.startswith("0x"):  # Ignore ENS names
        return fast_to_checksum_address(token_address)
    else:
        # Try ENS resolve
        ethereum_client = get_auto_ethereum_client()
        try:
            if resolved_address := ethereum_client.w3.ens.address(token_address):
                return resolved_address
        except (ValueError, Web3Exception):
            logger.warning("Cannot resolve %s ENS address", token_address)
    return None


@app.shared_task()
@close_gevent_db_connection_decorator
def update_token_info_from_token_list_task() -> int:
    """
    If there's at least one valid token list with at least 1 token, every token in the DB is marked as `not trusted`
    and then every token on the list is marked as `trusted`.

    `logoURI` is also stored for the tokens with logos

    :return: Number of tokens marked as `trusted`
    """
    tokens: list[TokenListToken] = []
    for token_list in TokenList.objects.all():
        try:
            tokens += token_list.get_tokens()
        except TokenListRetrievalException:
            logger.error("Cannot read tokens from %s", token_list)

    current_chain_id = get_ethereum_network().value

    # Some lists are meant to be used for multiple chains. Also, some lists have no address
    # or multiple address for bridged tokens, those cases are excluded for now
    filtered_tokens = [
        token
        for token in tokens
        if token.get("chainId") in (None, current_chain_id) and token.get("address")
    ]
    if not filtered_tokens:
        return 0

    tokens_updated_count = 0
    with transaction.atomic():
        Token.objects.update(trusted=False)
        for token in filtered_tokens:
            if token_address := _parse_token_address_from_token_list(token["address"]):
                logo_uri = token.get("logoURI") or ""
                if len(logo_uri) > 200:
                    # URLField has a limit of 200 chars
                    logger.error(
                        "Logo uri for token %s is exceeding 200 chars", token_address
                    )
                    logo_uri = ""
                tokens_updated_count += Token.objects.filter(
                    address=token_address
                ).update(logo_uri=logo_uri, trusted=True)
        return tokens_updated_count
