import contextlib
from functools import cache
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from celery import app
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress
from redis.exceptions import LockError

from safe_transaction_service.utils.utils import close_gevent_db_connection

from ..utils.tasks import LOCK_TIMEOUT, SOFT_TIMEOUT, only_one_running_task
from .indexers import (
    Erc20EventsIndexerProvider,
    FindRelevantElementsException,
    InternalTxIndexerProvider,
    ProxyFactoryIndexerProvider,
)
from .indexers.safe_events_indexer import SafeEventsIndexerProvider
from .indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider
from .models import InternalTxDecoded, SafeStatus, WebHook, WebHookType
from .services import (
    IndexingException,
    IndexServiceProvider,
    ReorgService,
    ReorgServiceProvider,
)

logger = get_task_logger(__name__)


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_erc20_events_task(self) -> Optional[int]:
    """
    Find and process ERC20/721 events for monitored addresses

    :return: Number of addresses processed
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of erc20/721 events")
            number_events = Erc20EventsIndexerProvider().start()
            logger.info(
                "Indexing of erc20/721 events task processed %d events", number_events
            )
            return number_events


@app.shared_task(
    bind=True,
)
def index_erc20_events_out_of_sync_task(
    self,
    block_process_limit: Optional[int] = None,
    block_process_limit_max: Optional[int] = None,
    addresses: Optional[ChecksumAddress] = None,
    number_of_addresses: Optional[int] = None,
) -> Optional[int]:
    """
    Find and process ERC20/721 events for monitored addresses out of sync (really behind)

    :return: Number of addresses processed
    """
    erc20_events_indexer = Erc20EventsIndexerProvider()
    if block_process_limit:
        erc20_events_indexer.block_process_limit = block_process_limit
    if block_process_limit_max:
        erc20_events_indexer.block_process_limit_max = block_process_limit_max

    current_block_number = erc20_events_indexer.ethereum_client.current_block_number
    addresses = addresses or [
        x.address
        for x in erc20_events_indexer.get_not_updated_addresses(current_block_number)[
            :number_of_addresses
        ]
    ]

    if not addresses:
        logger.info("No addresses to process")
    else:
        logger.info(
            "Start indexing of erc20/721 events for out of sync addresses %s", addresses
        )
        updated = False
        number_events_processed = 0
        while not updated:
            try:
                events_processed, updated = erc20_events_indexer.process_addresses(
                    addresses, current_block_number
                )
                number_events_processed += len(events_processed)
            except FindRelevantElementsException:
                pass

        logger.info(
            "Indexing of erc20/721 events for out of sync addresses task processed %d events",
            number_events_processed,
        )
        return number_events_processed


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_internal_txs_task(self) -> Optional[int]:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of internal txs")
            number_traces = InternalTxIndexerProvider().start()
            logger.info("Find internal txs task processed %d traces", number_traces)
            if number_traces:
                logger.info("Calling task to process decoded traces")
                process_decoded_internal_txs_task.delay()
            return number_traces


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_new_proxies_task(self) -> Optional[int]:
    """
    :return: Number of proxies created
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of new proxies")
            number_proxies = ProxyFactoryIndexerProvider().start()
            logger.info("Proxy indexing found %d proxies", number_proxies)
            if number_proxies:
                return number_proxies


@app.shared_task(
    bind=True,
    soft_time_limit=SOFT_TIMEOUT,
    time_limit=LOCK_TIMEOUT,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
def index_safe_events_task(self) -> Optional[int]:
    """
    Find and process for monitored addresses
    :return: Number of addresses processed
    """

    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of Safe events")
            number = SafeEventsIndexerProvider().start()
            logger.info("Find Safe events processed %d events", number)
            if number:
                logger.info("Calling task to process decoded traces")
                process_decoded_internal_txs_task.delay()
            return number


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task(self) -> Optional[int]:
    try:
        with only_one_running_task(self):
            count = InternalTxDecoded.objects.pending_for_safes().count()
            if not count:
                logger.info("No decoded internal txs to process")
            else:
                logger.info("%d decoded internal txs to process", count)
                for (
                    safe_to_process
                ) in InternalTxDecoded.objects.safes_pending_to_be_processed():
                    process_decoded_internal_txs_for_safe_task.delay(safe_to_process)
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_for_safe_task(
    self, safe_address: str
) -> Optional[int]:
    """
    Process decoded internal txs for one Safe. Processing decoded transactions is very slow and this way multiple
    Safes can be processed at the same time

    :param safe_address:
    :return:
    """
    try:
        with only_one_running_task(self, lock_name_suffix=safe_address):
            logger.info(
                "Start processing decoded internal txs for safe %s", safe_address
            )
            number_processed = 0
            batch = 100  # Process at most 100 decoded transactions for a single Safe
            tx_processor: SafeTxProcessor = SafeTxProcessorProvider()
            # Use slicing for memory issues
            while True:
                # Check if something is wrong during indexing
                last_safe_status = SafeStatus.objects.last_for_address(safe_address)
                if last_safe_status and last_safe_status.is_corrupted():
                    tx_processor.clear_cache()
                    # Find first corrupted safe status
                    for safe_status in SafeStatus.objects.filter(
                        address=safe_address
                    ).sorted_reverse_by_internal_tx():
                        if safe_status.is_corrupted():
                            message = (
                                f"A problem was found in SafeStatus with nonce={last_safe_status.nonce} "
                                f"on internal-tx-id={last_safe_status.internal_tx_id} "
                                f"tx-hash={last_safe_status.internal_tx.ethereum_tx_id} "
                                f"for safe-address={safe_address}, reindexing"
                            )
                            logger.error(message)
                            IndexServiceProvider().reprocess_addresses([safe_address])
                            raise ValueError(message)

                internal_txs_decoded = InternalTxDecoded.objects.pending_for_safe(
                    safe_address
                )[:batch]
                if not internal_txs_decoded:
                    break
                number_processed += len(
                    tx_processor.process_decoded_transactions(internal_txs_decoded)
                )
                if not number_processed:
                    break
                tx_processor.clear_cache()  # TODO Fix this properly
                logger.info("Processed %d decoded transactions", number_processed)
            if number_processed:
                logger.info(
                    "%d decoded internal txs successfully processed for safe %s",
                    number_processed,
                    safe_address,
                )
                return number_processed
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def check_reorgs_task(self) -> Optional[int]:
    """
    :return: Number of oldest block with reorg detected. `None` if not reorg found
    """
    try:
        with only_one_running_task(self):
            logger.info("Start checking of reorgs")
            reorg_service: ReorgService = ReorgServiceProvider()
            first_reorg_block_number = reorg_service.check_reorgs()
            if first_reorg_block_number:
                logger.warning(
                    "Reorg found for block-number=%d", first_reorg_block_number
                )
                # Stopping running tasks is not possible with gevent
                reorg_service.recover_from_reorg(first_reorg_block_number)
                return first_reorg_block_number
    except LockError:
        pass


@cache
def get_webhook_http_session(webhook_url: str) -> requests.Session:
    logger.debug("Getting http session for url=%s", webhook_url)
    return requests.Session()


@app.shared_task(
    autoretry_for=(IOError,), default_retry_delay=15, retry_kwargs={"max_retries": 3}
)
def send_webhook_task(address: Optional[str], payload: Dict[str, Any]) -> int:
    if not (address and payload):
        return 0

    try:
        webhooks = WebHook.objects.matching_for_address(address)
        if not webhooks:
            logger.debug("There is no webhook configured for address=%s", address)
            return 0

        sent_requests = 0
        webhook_type = WebHookType[payload["type"]]
        for webhook in webhooks:
            if not webhook.is_valid_for_webhook_type(webhook_type):
                continue

            full_url = webhook.url
            parsed_url = urlparse(full_url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"  # Remove url path for logging
            if webhook.address:
                logger.info(
                    "Sending webhook for address=%s base-url=%s and payload=%s",
                    address,
                    base_url,
                    payload,
                )
            else:  # Generic WebHook
                logger.info(
                    "Sending webhook for base-url=%s and payload=%s", base_url, payload
                )

            r = get_webhook_http_session(full_url).post(full_url, json=payload)
            if r.ok:
                logger.info(
                    "Webhook for base-url=%s and payload=%s was sent successfully",
                    base_url,
                    payload,
                )
            else:
                logger.warning(
                    "Webhook failed with status-code=%d posting to url=%s with content=%s",
                    r.status_code,
                    full_url,
                    r.content,
                )

            sent_requests += 1
        return sent_requests
    finally:
        close_gevent_db_connection()
