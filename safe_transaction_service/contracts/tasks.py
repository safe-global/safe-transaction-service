import datetime
from enum import Enum
from itertools import chain

from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress

from gnosis.eth.clients import EtherscanRateLimitError
from gnosis.safe.multi_send import MultiSend

from safe_transaction_service.history.models import (
    ModuleTransaction,
    MultisigTransaction,
)
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from .models import Contract
from .services.contract_metadata_service import get_contract_metadata_service

logger = get_task_logger(__name__)

TASK_SOFT_TIME_LIMIT = 30  # 30 seconds
TASK_TIME_LIMIT = 60  # 1 minute


class ContractAction(Enum):
    CREATED = 0
    UPDATED = 1
    NOT_MODIFIED = 2


@app.shared_task(soft_time_limit=TASK_SOFT_TIME_LIMIT, time_limit=TASK_TIME_LIMIT)
@close_gevent_db_connection_decorator
def create_missing_contracts_with_metadata_task() -> int:
    """
    Insert detected contracts the users are interacting with on database
    and retrieve metadata (name, abi) if possible

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


@app.shared_task(soft_time_limit=TASK_SOFT_TIME_LIMIT, time_limit=TASK_TIME_LIMIT)
@close_gevent_db_connection_decorator
def create_missing_multisend_contracts_with_metadata_task() -> int:
    """
    Insert detected contracts the users are interacting with using Multisend for the last day
    and retrieve metadata (name, abi) if possible

    :return: Number of contracts missing
    """
    addresses = set()
    for data in (
        MultisigTransaction.objects.trusted()
        .multisend()
        .with_data()
        .filter(created__gte=timezone.now() - datetime.timedelta(days=1))
        .values_list("data", flat=True)
        .iterator()
    ):
        for multisend_tx in MultiSend.from_transaction_data(bytes(data)):
            address = multisend_tx.to
            # Only index not existing contracts
            if not Contract.objects.filter(address=address).exists():
                addresses.add(address)

    for address in addresses:
        logger.info("Detected missing contract %s called using MultiSend", address)
        create_or_update_contract_with_metadata_task.apply_async(
            (address,), priority=1
        )  # Lowest priority
    return len(addresses)


@app.shared_task(soft_time_limit=TASK_SOFT_TIME_LIMIT, time_limit=TASK_TIME_LIMIT)
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
    soft_time_limit=TASK_SOFT_TIME_LIMIT,
    time_limit=TASK_TIME_LIMIT,
    autoretry_for=(EtherscanRateLimitError,),
    retry_backoff=10,
    retry_kwargs={"max_retries": 5},
)
@close_gevent_db_connection_decorator
def create_or_update_contract_with_metadata_task(
    address: ChecksumAddress,
) -> ContractAction:
    """
    Creates or updates a contract using 3rd party metadata (contract name, ABI...)

    :param address: Contract address
    :return: ContractAction
    """
    logger.info("Searching metadata for contract %s", address)
    contract_metadata_service = get_contract_metadata_service()
    contract_metadata = contract_metadata_service.get_contract_metadata(address)

    try:
        contract = Contract.objects.get(address=address)
        if contract_metadata and contract.update_from_metadata(contract_metadata):
            action = ContractAction.UPDATED
        else:
            action = ContractAction.NOT_MODIFIED
    except Contract.DoesNotExist:
        contract = Contract.objects.create_from_metadata(address, contract_metadata)
        action = ContractAction.CREATED

    logger.info(
        "%s contract with address=%s name=%s abi-found=%s",
        action,
        address,
        contract.name,
        contract.contract_abi is not None,
    )
    return action
