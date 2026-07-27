# SPDX-License-Identifier: FSL-1.1-MIT
import contextlib

from celery import app
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from safe_transaction_service.history.services import IndexingException
from safe_transaction_service.utils.celery import task_timeout
from safe_transaction_service.utils.tasks import LOCK_TIMEOUT, only_one_running_task

from .indexers import PolicyEventsIndexerProvider

logger = get_task_logger(__name__)


@app.shared_task(
    bind=True,
    autoretry_for=(IndexingException, IOError),
    default_retry_delay=15,
    retry_kwargs={"max_retries": 3},
)
@task_timeout(timeout_seconds=LOCK_TIMEOUT)
def index_policy_events_task(self) -> tuple[int, int] | None:
    """
    :return: Tuple of number of policy events indexed and number of blocks processed
    """
    with contextlib.suppress(LockError):
        with only_one_running_task(self):
            logger.info("Start indexing of policy guard events")
            (
                number_events,
                number_of_blocks_processed,
            ) = PolicyEventsIndexerProvider().start()
            logger.info("Policy indexing found %d events", number_events)
            return number_events, number_of_blocks_processed
