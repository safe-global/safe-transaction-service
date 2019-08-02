from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings
from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe
from redis import Redis
from redis.exceptions import LockError

from .models import MultisigConfirmation
from .services.proxy_factory_indexer import ProxyIndexerServiceProvider

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds


@app.shared_task(bind=True)
def check_approve_transaction_task(self, safe_address: str, safe_tx_hash: str,
                                   transaction_hash: str, owner: str, retry: bool = True) -> None:
    safe_reorg_blocks = settings.SAFE_REORG_BLOCKS
    ethereum_client = EthereumClientProvider()
    safe = Safe(safe_address, ethereum_client)

    current_block_number = ethereum_client.current_block_number
    block_identifier = current_block_number - settings.SAFE_REORG_BLOCKS
    try:
        multisig_confirmation = MultisigConfirmation.objects.select_related(
            'multisig_transaction'
        ).get(multisig_transaction_id=safe_tx_hash,
              owner=owner,
              transaction_hash=transaction_hash)

        multisig_transaction = multisig_confirmation.multisig_transaction

        assert safe_address == multisig_transaction.safe

        is_executed_latest = multisig_transaction.nonce < safe.retrieve_nonce(block_identifier='latest')

        # If tx is executed hash in `approvedHashes` will be deleted to free storage and use gas for tx
        is_approved_latest = safe.retrieve_is_hash_approved(multisig_confirmation.owner,
                                                            safe_tx_hash,
                                                            block_identifier='latest')

        is_approved_prev = safe.retrieve_is_hash_approved(multisig_confirmation.owner,
                                                          safe_tx_hash,
                                                          block_identifier=block_identifier)

        transaction_data = ethereum_client.get_transaction(transaction_hash)

        if transaction_data:
            tx_block_number = transaction_data['blockNumber']
            if transaction_data['blockNumber'] != multisig_confirmation.block_number:
                if is_approved_prev and not is_approved_latest and not is_executed_latest:
                    # Detected reorg, multisig transaction not executed, also confirmation
                    # not approved either before and after blocks check
                    multisig_confirmation.delete()
                    return
                else:
                    # Update block number of stored confirmation
                    multisig_confirmation.block_number = tx_block_number
                    multisig_confirmation.save()

            if is_executed_latest:
                if not multisig_transaction.mined:
                    multisig_transaction.set_mined()
                return
            elif is_approved_latest:
                multisig_confirmation.set_mined()
                return

        else:  # Not transaction_data:
            # Check if more then X blocks have passed from the block number the transaction was created in DB
            if current_block_number - multisig_confirmation.block_number > safe_reorg_blocks:
                # Detected reorg, delete confirmation
                multisig_confirmation.delete()
                return

        if retry:
            self.retry(countdown=COUNTDOWN)

    except MultisigConfirmation.DoesNotExist:
        logger.warning('Multisig confirmation for safe=%s and transaction_hash=%s does not exist',
                       safe_address,
                       transaction_hash)


@app.shared_task(bind=True)
def index_new_proxies(self) -> int:
    """
    :param self:
    :return: Number of proxies created
    """

    redis = Redis.from_url(settings.REDIS_URL)
    try:
        with redis.lock('tasks:index_new_proxies', blocking_timeout=1, timeout=60 * 30):
            proxy_factory_addresses = ['0x12302fE9c02ff50939BaAaaf415fc226C078613C']
            proxy_indexer_service = ProxyIndexerServiceProvider()

            new_monitored_addresses = 0
            updated = False

            while not updated:
                created_objects, updated = proxy_indexer_service.process_addresses(proxy_factory_addresses)
                new_monitored_addresses += len(created_objects)
            if new_monitored_addresses:
                logger.info('Indexed new %d proxies', new_monitored_addresses)

            return new_monitored_addresses
    except LockError:
        pass
