from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings
from eth_abi import decoding

from .ethereum_service import EthereumServiceProvider
from .models import MultisigConfirmation
from .contracts import get_safe_team_contract


logger = get_task_logger(__name__)

ethereum_service = EthereumServiceProvider()


COUNTDOWN = 60 # seconds


def read_data_from_stream(self, stream):
    data = stream.read(self.data_byte_size)
    return data

# Workaround to fix InsufficientDataBytes exception raised by a wrong value format returned by
decoding.Fixed32ByteSizeDecoder.read_data_from_stream = read_data_from_stream


@app.shared_task(bind=True)
def check_approve_transaction(self, safe_address: str, contract_transaction_hash: str, owner: str, retry: bool=True) -> None:
    w3 = ethereum_service.w3  # Web3 instance
    safe_contract = get_safe_team_contract(w3, safe_address)

    block_identifier = ethereum_service.current_block_number - settings.SAFE_REORG_BLOCKS
    multisig_confirmation = MultisigConfirmation.objects.get(contract_transaction_hash=contract_transaction_hash, owner=owner)

    is_executed_latest = safe_contract.functions.isExecuted(multisig_confirmation.contract_transaction_hash).call(
        block_identifier='latest')
    is_executed_prev = safe_contract.functions.isExecuted(multisig_confirmation.contract_transaction_hash).call(
        block_identifier=block_identifier)
    is_approved_latest = safe_contract.functions.isApproved(contract_transaction_hash, multisig_confirmation.owner).call(
        block_identifier='latest')
    is_approved_prev = safe_contract.functions.isApproved(contract_transaction_hash, multisig_confirmation.owner).call(
        block_identifier=block_identifier)

    if is_approved_prev and not is_approved_latest:
        # reorg, delete confirmation
        multisig_confirmation.delete()
    elif not is_approved_latest and is_executed_latest:
        # Check if multisig transaction executed
        multisig_transaction = multisig_confirmation.multisig_transaction
        if not multisig_transaction.status:
            multisig_transaction.status = is_executed_latest
            multisig_transaction.save()
    elif is_approved_latest:
        multisig_confirmation.status = is_approved_latest
        multisig_confirmation.save()

        if is_executed_latest:
            # Check if multisig transaction executed
            multisig_transaction = multisig_confirmation.multisig_transaction
            if not multisig_transaction.status:
                multisig_transaction.status = is_executed_latest
                multisig_transaction.save()
    elif retry:
        self.retry(countdown=COUNTDOWN)
