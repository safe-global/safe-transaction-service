from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings

from .ethereum_service import EthereumServiceProvider
from .models import MultisigConfirmation
from .contracts import get_safe_team_contract


logger = get_task_logger(__name__)

ethereum_service = EthereumServiceProvider()


COUNTDOWN = 60 # seconds


@app.shared_task(bind=True)
def check_approve_transaction(self, safe_address: str, contract_transaction_hash: str, retry: bool=True) -> None:
    # TODO add tests and code review
    w3 = ethereum_service.w3  # Web3 instance
    safe_contract = get_safe_team_contract(w3, safe_address)

    multisig_confirmation = MultisigConfirmation.objects.get(transaction_hash=contract_transaction_hash)

    is_executed_latest = safe_contract.functions.isExecuted(multisig_confirmation.contract_transaction_hash).call(
        block_identifier='latest')
    is_executed_prev = safe_contract.functions.isExecuted(multisig_confirmation.contract_transaction_hash).call(
        block_identifier=ethereum_service.current_block_number - settings.SAFE_REORG_BLOCKS)
    is_approved_latest = safe_contract.functions.isApproved(contract_transaction_hash, multisig_confirmation.owner).call(
        block_identifier='latest'
    )
    is_approved_prev = safe_contract.functions.isApproved(contract_transaction_hash, multisig_confirmation.owner).call(
        block_identifier=ethereum_service.current_block_number - settings.SAFE_REORG_BLOCKS
    )

    if is_approved_prev and not is_approved_latest:
        # reorg, delete confirmation
        multisig_confirmation.delete()
    elif is_approved_latest:
        multisig_confirmation.status = is_approved_latest
        multisig_confirmation.save()

        if is_executed_latest:
            # Check if multisig transaction executed
            multisig_transaction = multisig_confirmation.multisig_transaction
            if not multisig_transaction.status:
                multisig_transaction.status = is_executed_latest
                multisig_transaction.save()
    # elif is_executed_prev and not is_executed_latest:
    #     confirmations = multisig_confirmation.multisig_transaction.confirmations
    #     if confirmations.count() == safe_contract.functions.getThreshold().call(block_identifier='latest'):
    #         # reorg
    #         multisig_confirmation.delete()
    elif retry:
        self.retry(countdown=COUNTDOWN)
