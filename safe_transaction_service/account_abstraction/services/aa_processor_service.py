import logging
from functools import cache
from typing import List, Optional, Sequence, Tuple

from django.conf import settings
from django.db import transaction

from eth_typing import ChecksumAddress, HexStr
from hexbytes import HexBytes
from web3.types import LogReceipt

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.account_abstraction import (
    BundlerClient,
    BundlerClientException,
    UserOperation,
    UserOperationReceipt,
)
from gnosis.eth.utils import fast_to_checksum_address
from gnosis.safe.account_abstraction import SafeOperation
from gnosis.safe.safe_signature import SafeSignature

from safe_transaction_service.history import models as history_models

from ..constants import USER_OPERATION_EVENT_TOPICS
from ..models import SafeOperation as SafeOperationModel
from ..models import SafeOperationConfirmation as SafeOperationConfirmationModel
from ..models import UserOperation as UserOperationModel
from ..models import UserOperationReceipt as UserOperationReceiptModel

logger = logging.getLogger(__name__)


class AaProcessorServiceException(Exception):
    pass


class UserOperationFailed(AaProcessorServiceException):
    pass


class ExecutionFromSafeModuleNotDetected(AaProcessorServiceException):
    pass


@cache
def get_aa_processor_service() -> "AaProcessorService":
    ethereum_client = EthereumClientProvider()
    bundler_client = (
        BundlerClient(settings.ETHEREUM_4337_BUNDLER_URL)
        if settings.ETHEREUM_4337_BUNDLER_URL
        else None
    )
    if not bundler_client:
        logger.warning("Ethereum 4337 bundler client was not configured")
    supported_entry_points = settings.ETHEREUM_4337_SUPPORTED_ENTRY_POINTS
    return AaProcessorService(ethereum_client, bundler_client, supported_entry_points)


class AaProcessorService:
    """
    Account Abstraction Transaction Processor

    From ``EthereumTxs`` it can detect and index ``SafeOperations``
    """

    def __init__(
        self,
        ethereum_client: EthereumClient,
        bundler_client: Optional[BundlerClient],
        supported_entry_points: Sequence[ChecksumAddress],
    ):
        self.ethereum_client = ethereum_client
        self.bundler_client = bundler_client
        self.supported_entry_points = supported_entry_points

    def get_user_operation_logs(
        self, safe_address: ChecksumAddress, logs: [Sequence[LogReceipt]]
    ) -> List[LogReceipt]:
        """
        :param safe_address:
        :param logs:
        :return: Logs for ``UserOperation`` from entrypoint if detected
        """
        return [
            log
            for log in logs
            if (
                len(log["topics"]) == 4
                and HexBytes(log["topics"][0]) in USER_OPERATION_EVENT_TOPICS
                and fast_to_checksum_address(log["address"])
                in self.supported_entry_points  # Only index supported entryPoints
                and fast_to_checksum_address(log["topics"][2][-40:])
                == safe_address  # Check sender
            )
        ]

    def is_user_operation_indexed(self, user_operation_hash: HexStr) -> bool:
        """
        If Receipt is stored, transaction has already been indexed

        :param user_operation_hash:
        :return: ``True`` if indexed, ``False`` otherwise
        """
        return UserOperationReceiptModel.objects.filter(
            user_operation__hash=user_operation_hash
        ).exists()

    def index_safe_operation_confirmations(
        self,
        signature: bytes,
        safe_operation_model: SafeOperationModel,
        safe_operation: SafeOperation,
    ) -> List[SafeOperationConfirmationModel]:
        """
        Creates missing ``SafeOperationConfirmations``

        :param signature:
        :param safe_operation_model:
        :param safe_operation:
        :return: List of ``SafeOperationConfirmationModel`` created (even if they were already on database)
        """
        parsed_signatures = SafeSignature.parse_signature(
            signature,
            safe_operation_model.hash,
            safe_operation.get_safe_operation_hash_preimage(
                self.ethereum_client.get_chain_id(), safe_operation_model.module_address
            ),
        )

        safe_operation_confirmations = []
        for parsed_signature in parsed_signatures:
            safe_operation_confirmation, _ = (
                SafeOperationConfirmationModel.objects.get_or_create(
                    safe_operation=safe_operation_model,
                    owner=parsed_signature.owner,
                    defaults={
                        "signature": parsed_signature.export_signature(),
                        "signature_type": parsed_signature.signature_type.value,
                    },
                )
            )
            safe_operation_confirmations.append(safe_operation_confirmation)
        return safe_operation_confirmations

    def index_safe_operation(
        self,
        user_operation_model: UserOperationModel,
        user_operation: UserOperation,
        user_operation_receipt: UserOperationReceipt,
    ) -> Tuple[SafeOperationModel, SafeOperation]:
        """
        Creates or updates a Safe Operation

        :param user_operation_model: Required due to the ForeignKey to ``UserOperation``
        :param user_operation: To build SafeOperation from
        :param user_operation_receipt: For detecting the Safe module address
        :return: Tuple with ``SafeOperationModel`` stored in Database and ``SafeOperation``
        """

        if not (module_address := user_operation_receipt.get_module_address()):
            raise ExecutionFromSafeModuleNotDetected(
                f"Cannot find ExecutionFromModuleSuccess for user-operation-hash={user_operation.user_operation_hash.hex()}"
            )

        # Build SafeOperation from UserOperation
        safe_operation = SafeOperation.from_user_operation(user_operation)

        safe_operation_hash = safe_operation.get_safe_operation_hash(
            self.ethereum_client.get_chain_id(), module_address
        )

        # Store SafeOperation
        safe_operation_model, created = SafeOperationModel.objects.get_or_create(
            hash=safe_operation_hash,
            defaults={
                "user_operation": user_operation_model,
                "valid_after": safe_operation.valid_after_as_datetime,
                "valid_until": safe_operation.valid_until_as_datetime,
                "module_address": module_address,
            },
        )
        if not created:
            logger.debug(
                "[%s] safe-operation-hash=%s for user-operation-hash=%s was already indexed",
                user_operation_model.sender,
                HexBytes(safe_operation_hash).hex(),
                user_operation.user_operation_hash.hex(),
            )
        self.index_safe_operation_confirmations(
            HexBytes(user_operation.signature), safe_operation_model, safe_operation
        )
        return safe_operation_model, safe_operation

    def index_user_operation_receipt(
        self, user_operation_model: UserOperationModel
    ) -> Tuple[UserOperationReceiptModel, UserOperationReceipt]:
        """
        Stores UserOperationReceipt. Can never be updated as if ``UserOperationReceipt`` is on database indexing
        ``UserOperation`` is not required

        :param user_operation_model: Required due to the ForeignKey to ``UserOperation``
        :return: Tuple with ``UserOperation`` and ``UserOperationReceipt``
        """
        safe_address = user_operation_model.sender
        user_operation_hash = HexBytes(user_operation_model.hash).hex()
        tx_hash = HexBytes(user_operation_model.ethereum_tx_id).hex()
        logger.debug(
            "[%s] Retrieving UserOperation Receipt with user-operation-hash=%s on tx-hash=%s",
            safe_address,
            user_operation_hash,
            tx_hash,
        )
        user_operation_receipt = self.bundler_client.get_user_operation_receipt(
            user_operation_hash
        )
        if not user_operation_receipt.success:
            raise UserOperationFailed(
                f"UserOperation with user-operation-hash={user_operation_hash} failed"
            )

        # Use event `Deposited (index_topic_1 address account, uint256 totalDeposit)`
        # to get deposited funds
        deposited = user_operation_receipt.get_deposit()

        logger.debug(
            "[%s] Storing UserOperation Receipt with user-operation=%s on tx-hash=%s",
            safe_address,
            user_operation_hash,
            tx_hash,
        )

        return (
            UserOperationReceiptModel.objects.create(
                user_operation=user_operation_model,
                actual_gas_cost=user_operation_receipt.actual_gas_cost,
                actual_gas_used=user_operation_receipt.actual_gas_used,
                success=user_operation_receipt.success,
                reason=user_operation_receipt.reason,
                deposited=deposited,
            ),
            user_operation_receipt,
        )

    @transaction.atomic
    def index_user_operation(
        self,
        safe_address: ChecksumAddress,
        log: LogReceipt,
        ethereum_tx: history_models.EthereumTx,
    ) -> Tuple[UserOperationModel, UserOperation]:
        """
        Index ``UserOperation``, ``SafeOperation`` and ``UserOperationReceipt`` for the given ``UserOperation`` log

        :param safe_address: to prevent indexing UserOperations from other address
        :param log: log event with the ``UserOperation`` emitted by the entryPoint
        :param ethereum_tx: Stored EthereumTx in database containing the ``UserOperation``
        :return: tuple of ``UserOperationModel`` and ``UserOperation``
        """
        user_operation_hash = HexBytes(log["topics"][1]).hex()
        # If the UserOperationReceipt is present, UserOperation was already processed and mined
        if self.is_user_operation_indexed(user_operation_hash):
            logger.warning(
                "[%s] user-operation-hash=%s receipt was already indexed",
                safe_address,
                user_operation_hash,
            )
        else:
            logger.debug(
                "[%s] Retrieving UserOperation from Bundler with user-operation-hash=%s on tx-hash=%s",
                safe_address,
                user_operation_hash,
                ethereum_tx.tx_hash,
            )
            user_operation = self.bundler_client.get_user_operation_by_hash(
                user_operation_hash
            )
            if not user_operation:
                self.bundler_client.get_user_operation_by_hash.cache_clear()
                raise BundlerClientException(
                    f"user-operation={user_operation_hash} returned `null`"
                )

            try:
                user_operation_model = UserOperationModel.objects.get(
                    hash=user_operation_hash
                )
                logger.debug(
                    "[%s] Updating UserOperation with user-operation=%s on tx-hash=%s",
                    safe_address,
                    user_operation_hash,
                    ethereum_tx.tx_hash,
                )
                user_operation_model.signature = user_operation.signature
                user_operation_model.ethereum_tx = ethereum_tx
                user_operation_model.save(update_fields=["signature", "ethereum_tx"])
            except UserOperationModel.DoesNotExist:
                logger.debug(
                    "[%s] Storing UserOperation with user-operation=%s on tx-hash=%s",
                    safe_address,
                    user_operation_hash,
                    ethereum_tx.tx_hash,
                )
                user_operation_model = UserOperationModel.objects.create(
                    ethereum_tx=ethereum_tx,
                    hash=user_operation_hash,
                    sender=user_operation.sender,
                    nonce=user_operation.nonce,
                    init_code=user_operation.init_code,
                    call_data=user_operation.call_data,
                    call_data_gas_limit=user_operation.call_gas_limit,
                    verification_gas_limit=user_operation.verification_gas_limit,
                    pre_verification_gas=user_operation.pre_verification_gas,
                    max_fee_per_gas=user_operation.max_fee_per_gas,
                    max_priority_fee_per_gas=user_operation.max_priority_fee_per_gas,
                    paymaster=user_operation.paymaster,
                    paymaster_data=user_operation.paymaster_data,
                    signature=user_operation.signature,
                    entry_point=user_operation.entry_point,
                )

            _, user_operation_receipt = self.index_user_operation_receipt(
                user_operation_model
            )
            self.index_safe_operation(
                user_operation_model, user_operation, user_operation_receipt
            )

            return user_operation_model, user_operation

    def process_aa_transaction(
        self, safe_address: ChecksumAddress, ethereum_tx: history_models.EthereumTx
    ) -> int:
        """
        Check if transaction contains any 4337 UserOperation for the provided `safe_address`.
        Function is cached to prevent reprocessing the same transaction.

        :param safe_address: Sender to check in UserOperation
        :param ethereum_tx: EthereumTx to check for UserOperations
        :return: Number of detected ``UserOperations`` in transaction
        """
        aa_logs = self.get_user_operation_logs(safe_address, ethereum_tx.logs)
        number_detected_user_operations = len(aa_logs)
        if not self.bundler_client:
            logger.debug(
                "Detected 4337 User Operation but bundler client was not configured"
            )
            return number_detected_user_operations

        for log in aa_logs:
            try:
                self.index_user_operation(safe_address, log, ethereum_tx)
            except BundlerClientException as exc:
                logger.error(
                    "[%s] Error retrieving user-operation from bundler API: %s",
                    safe_address,
                    exc,
                )
            except AaProcessorServiceException as exc:
                logger.error(
                    "[%s] Error processing user-operation: %s",
                    safe_address,
                    exc,
                )

        return number_detected_user_operations
