from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings
from django.db import transaction
from hexbytes import HexBytes
from redis import Redis
from redis.exceptions import LockError

from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe, SafeTx

from .indexers import InternalTxIndexerProvider, ProxyIndexerServiceProvider
from .models import InternalTxDecoded, MultisigConfirmation, SafeStatus, MultisigTransaction

logger = get_task_logger(__name__)


COUNTDOWN = 60  # seconds
LOCK_TIMEOUT = 60 * 10  # 10 minutes


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


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
                       safe_address, transaction_hash)


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_new_proxies_task() -> int:
    """
    :return: Number of proxies created
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_new_proxies_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
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


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def index_internal_txs_task() -> int:
    """
    Find and process internal txs for monitored addresses
    :return: Number of addresses processed
    """

    redis = get_redis()
    try:
        with redis.lock('tasks:index_internal_txs_task', blocking_timeout=1, timeout=LOCK_TIMEOUT):
            number_addresses = InternalTxIndexerProvider().process_all()
            logger.info('Find internal txs task processed %d addresses', number_addresses)
            return number_addresses
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def process_decoded_internal_txs_task() -> int:
    redis = get_redis()
    try:
        with redis.lock('tasks:process_decoded_internal_txs_task', blocking_timeout=1, timeout=PROCESS_DECODED_TIMEOUT):
            number_processed = 0
            for internal_tx_decoded in InternalTxDecoded.objects.pending():
                function_name = internal_tx_decoded.function_name
                arguments = internal_tx_decoded.arguments
                contract_address = internal_tx_decoded.internal_tx.to
                processed = True
                with transaction.atomic():
                    if function_name == 'setup':
                        owners = arguments['_owners']
                        threshold = arguments['_threshold']
                        SafeStatus.objects.create(internal_tx=internal_tx_decoded.internal_tx, address=contract_address,
                                                  owners=owners, threshold=threshold, nonce=0)
                    elif function_name in ('addOwnerWithThreshold', 'removeOwner', 'removeOwnerWithThreshold'):
                        owner = arguments['owner']
                        threshold = arguments['_threshold']
                        safe_status = SafeStatus.objects.last_for_address(contract_address)
                        nonce = safe_status.nonce
                        owners = list(safe_status.owners)
                        if function_name == 'addOwnerWithThreshold':
                            owners.append(owner)
                        else:  # removeOwner, removeOwnerWithThreshold
                            owners.remove(owner)
                        SafeStatus.objects.create(internal_tx=internal_tx_decoded.internal_tx, address=contract_address,
                                                  owners=owners, threshold=threshold, nonce=nonce)
                    elif function_name == 'swapOwner':
                        old_owner = arguments['oldOwner']
                        new_owner = arguments['newOwner']
                        safe_status = SafeStatus.objects.last_for_address(contract_address)
                        nonce = safe_status.nonce
                        threshold = safe_status.threshold
                        owners = list(safe_status.owners)
                        owners.remove(old_owner)
                        owners.append(new_owner)
                        SafeStatus.objects.create(internal_tx=internal_tx_decoded.internal_tx, address=contract_address,
                                                  owners=owners, threshold=threshold, nonce=nonce)
                    elif function_name == 'changeThreshold':
                        safe_status = SafeStatus.objects.last_for_address(contract_address)
                        nonce = safe_status.nonce
                        threshold = arguments['_threshold']
                        owners = list(safe_status.owners)
                        SafeStatus.objects.create(internal_tx=internal_tx_decoded.internal_tx, address=contract_address,
                                                  owners=owners, threshold=threshold, nonce=nonce)
                    elif function_name == 'execTransaction':
                        safe_status = SafeStatus.objects.last_for_address(contract_address)
                        nonce = safe_status.nonce
                        threshold = safe_status.threshold
                        owners = safe_status.owners
                        safe_tx = SafeTx(None, contract_address, arguments['to'], arguments['value'], arguments['data'],
                                         arguments['operation'], arguments['safeTxGas'], arguments['baseGas'],
                                         arguments['gasPrice'], arguments['gasToken'], arguments['refundReceiver'],
                                         HexBytes(arguments['signatures']), safe_nonce=nonce)
                        safe_tx_hash = safe_tx.safe_tx_hash

                        ethereum_tx = internal_tx_decoded.internal_tx.ethereum_tx
                        multisig_tx, created = MultisigTransaction.objects.get_or_create(
                            safe_tx_hash=safe_tx_hash,
                            defaults={
                                'ethereum_tx': ethereum_tx,
                                'to': safe_tx.to,
                                'value': safe_tx.value,
                                'data': safe_tx.data,
                                'operation': safe_tx.operation,
                                'safe_tx_gas': safe_tx.safe_tx_gas,
                                'base_gas': safe_tx.base_gas,
                                'gas_price': safe_tx.gas_price,
                                'gas_token': safe_tx.gas_token,
                                'refund_receiver': safe_tx.refund_receiver,
                                'nonce': safe_tx.safe_nonce,
                            })
                        if not created and not multisig_tx.ethereum_tx:
                            multisig_tx.ethereum_tx = ethereum_tx
                            multisig_tx.save(update_fields=['ethereum_tx'])

                        SafeStatus.objects.create(internal_tx=internal_tx_decoded.internal_tx, address=contract_address,
                                                  owners=owners, threshold=threshold, nonce=nonce + 1)
                    elif function_name == 'approveHash':
                        multisig_transaction_hash = arguments['hashToApprove']
                        ethereum_tx = internal_tx_decoded.internal_tx.ethereum_tx
                        owner = internal_tx_decoded.internal_tx._from
                        try:
                            multisig_transaction = MultisigTransaction.objects.get(
                                safe_tx_hash=multisig_transaction_hash
                            )
                        except MultisigTransaction.DoesNotExist:
                            multisig_transaction = None

                        MultisigConfirmation.objects.get_or_create(multisig_transaction_hash=multisig_transaction_hash,
                                                                   owner=owner,
                                                                   defaults={
                                                                       'multisig_transaction': multisig_transaction,
                                                                       'ethereum_tx': ethereum_tx,
                                                                   })
                    else:
                        processed = False
                    if processed:
                        number_processed += 1
                        internal_tx_decoded.set_processed()
            if number_processed:
                logger.info('%d decoded internal txs processed', number_processed)
            return number_processed
    except LockError:
        pass
