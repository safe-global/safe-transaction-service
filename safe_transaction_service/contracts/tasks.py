from typing import Sequence

from celery import app
from celery.utils.log import get_task_logger
from django.db import IntegrityError, transaction

from safe_transaction_service.contracts.models import Contract
from safe_transaction_service.history.utils import (close_gevent_db_connection,
                                                    get_redis)

logger = get_task_logger(__name__)


@app.shared_task()
def index_contracts(addresses: Sequence[str]):
    try:
        for address in addresses:
            try:
                with transaction.atomic():
                    if contract := Contract.objects.create_from_address(address):
                        logger.info('Indexed contract with address=%s name=%s abi-present=%s',
                                    address, contract.name, bool(contract.contract_abi.abi))
            except IntegrityError:
                logger.warning('Contract with address=%s was already created', address)
    finally:
        close_gevent_db_connection()
