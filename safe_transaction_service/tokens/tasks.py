from typing import Optional

from celery import app
from celery.utils.log import get_task_logger

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork

from safe_transaction_service.history.utils import close_gevent_db_connection

from .models import Token

logger = get_task_logger(__name__)


@app.shared_task()
def fix_pool_tokens_task() -> Optional[int]:
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
