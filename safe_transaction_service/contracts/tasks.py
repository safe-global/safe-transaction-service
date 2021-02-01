from typing import Sequence

from django.db import IntegrityError, transaction

from celery import app
from celery.utils.log import get_task_logger

from gnosis.eth import EthereumClientProvider

from safe_transaction_service.history.utils import close_gevent_db_connection

from .models import Contract

logger = get_task_logger(__name__)


@app.shared_task()
def index_contracts_metadata_task(addresses: Sequence[str]):
    ethereum_client = EthereumClientProvider()
    ethereum_network = ethereum_client.get_network()
    try:
        for address in addresses:
            try:
                with transaction.atomic():
                    if contract := Contract.objects.create_from_address(address, network_id=ethereum_network.value):
                        logger.info('Indexed contract with address=%s name=%s abi-present=%s',
                                    address, contract.name, bool(contract.contract_abi.abi))
                    else:
                        Contract.objects.create(address=address)
            except IntegrityError:
                logger.warning('Contract with address=%s was already created', address)
    finally:
        close_gevent_db_connection()
