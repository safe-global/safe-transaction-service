from itertools import chain

from django.db import IntegrityError, transaction

from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress

from gnosis.eth.clients import EtherscanRateLimitError

from safe_transaction_service.history.models import (
    ModuleTransaction,
    MultisigTransaction,
)
from safe_transaction_service.utils.ethereum import get_ethereum_network
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from .models import Contract

logger = get_task_logger(__name__)


@app.shared_task()
@close_gevent_db_connection_decorator
def create_missing_contracts_with_metadata_task() -> int:
    """
    Insert detected contracts the users are interacting with on database and retrieve metadata (name, abi) if possible

    :return: Number of contracts missing
    """
    addresses = chain(
        MultisigTransaction.objects.not_indexed_metadata_contract_addresses().iterator(),
        ModuleTransaction.objects.not_indexed_metadata_contract_addresses().iterator(),
    )
    i = 0
    for address in addresses:
        logger.info("Detected missing contract %s", address)
        create_or_update_contract_with_metadata_task.apply_async(
            (address,), priority=1
        )  # Lowest priority
        i += 1
    return i


@app.shared_task()
@close_gevent_db_connection_decorator
def reindex_contracts_without_metadata_task() -> int:
    """
    Try to reindex existing contracts without metadata

    :return: Number of contracts missing
    """
    i = 0
    for address in (
        Contract.objects.without_metadata().values_list("address", flat=True).iterator()
    ):
        logger.info("Reindexing contract %s", address)
        create_or_update_contract_with_metadata_task.apply_async(
            (address,), priority=1
        )  # Lowest priority
        i += 1
    return i


@app.shared_task(
    autoretry_for=(EtherscanRateLimitError,),
    retry_backoff=10,
    retry_kwargs={"max_retries": 5},
)
@close_gevent_db_connection_decorator
def create_or_update_contract_with_metadata_task(address: ChecksumAddress):
    logger.info("Searching metadata for contract %s", address)
    ethereum_network = get_ethereum_network()
    try:
        with transaction.atomic():
            contract = Contract.objects.create_from_address(
                address, network=ethereum_network
            )
            action = "Created"
    except IntegrityError:
        contract = Contract.objects.get(address=address)
        if contract.sync_abi_from_api():
            action = "Updated"
        else:
            action = "Not modified"

    logger.info(
        "%s contract with address=%s name=%s abi-found=%s",
        action,
        address,
        contract.name,
        contract.contract_abi is not None,
    )
