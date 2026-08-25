# SPDX-License-Identifier: FSL-1.1-MIT
import datetime
import logging
from functools import cache

from django.db import models
from django.db.models import Case, Index, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Now

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField,
    HexV2Field,
    Keccak256Field,
)
from safe_eth.safe.enums import SafeOperationEnum
from safe_eth.util.util import to_0x_hex_str
from web3.types import EventData

from safe_transaction_service.history import models as history_models

logger = logging.getLogger(__name__)

# `AccessSelector.createFallback(operation)` leaves target and selector empty, making the
# policy the catch-all for that operation
FALLBACK_SELECTOR = b"\x00" * 4

# The guard can only emit `CALL` and `DELEGATECALL`, `SafeOperationEnum` is reused so the API
# renders operations like `MultisigTransaction` and `ModuleTransaction` do
POLICY_OPERATIONS = (SafeOperationEnum.CALL, SafeOperationEnum.DELEGATE_CALL)
POLICY_OPERATION_VALUES = frozenset(operation.value for operation in POLICY_OPERATIONS)


class SafePolicyGuard(history_models.MonitoredAddress):
    """`SafePolicyGuard` deployment whose events are indexed."""

    class Meta:
        verbose_name = "Safe policy guard"
        verbose_name_plural = "Safe policy guards"
        ordering = ["tx_block_number"]


class PolicyContractManager(models.Manager):
    @cache  # noqa: B019
    def get_name_for_address(self, address: ChecksumAddress) -> str | None:
        """
        :return: Name of the policy deployed on `address`, `None` if it is not known
        """
        try:
            return self.values_list("name", flat=True).get(address=address)
        except self.model.DoesNotExist:
            return None


class PolicyContract(models.Model):
    """
    Known policy implementation. The name selects the decoder for the `data` a Safe
    configured the policy with, see `policies.decoders`.
    """

    objects = PolicyContractManager()
    address = EthereumAddressBinaryField(primary_key=True)
    name = models.CharField(max_length=64, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} - {self.address}"


class PolicyEngineEvent(models.Model):
    """Abstract base for every log emitted by a `SafePolicyGuard`."""

    ethereum_tx = models.ForeignKey(history_models.EthereumTx, on_delete=models.CASCADE)
    log_index = models.PositiveIntegerField()
    block_number = models.PositiveIntegerField()
    timestamp = models.DateTimeField(db_index=True)
    guard = EthereumAddressBinaryField()  # Contract that emitted the log
    safe = EthereumAddressBinaryField(db_index=True)

    class Meta:
        abstract = True

    @staticmethod
    def _base_parameters_from_decoded_event(event_data: EventData) -> dict:
        """
        :return: Field values shared by every policy guard event
        :raises EthereumBlock.DoesNotExist: Block is missing, meaning a reorg happened. The
            block is marked as not confirmed so the reorg service can recover from it
        """
        try:
            timestamp = history_models.EthereumBlock.objects.get_timestamp_by_hash(
                event_data["blockHash"]
            )
        except history_models.EthereumBlock.DoesNotExist:
            history_models.EthereumTx.objects.get(
                event_data["transactionHash"]
            ).block.set_not_confirmed()
            raise

        return {
            "ethereum_tx_id": event_data["transactionHash"],
            "log_index": event_data["logIndex"],
            "block_number": event_data["blockNumber"],
            "timestamp": timestamp,
            "guard": event_data["address"],
            "safe": event_data["args"]["safe"],
        }

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> "PolicyEngineEvent":
        raise NotImplementedError


class PolicyConfirmationQuerySet(models.QuerySet):
    def current(self):
        """
        :return: Latest confirmation per `(safe, target, selector, operation)`, which is the
            configuration currently stored by the guard
        """
        return self.order_by(
            "safe", "target", "selector", "operation", "-block_number", "-log_index"
        ).distinct("safe", "target", "selector", "operation")

    def active(self):
        """
        :return: Currently enforced policies. A confirmation with an empty policy is a removal

        The removals must be excluded *after* deduplicating, otherwise the previous
        confirmation of a removed access selector becomes the latest one and is reported as
        enforced, so `current()` has to be resolved in a subquery
        """
        return self.filter(pk__in=self.current().values("pk")).exclude(
            policy=NULL_ADDRESS
        )


class PolicyConfirmation(PolicyEngineEvent):
    """
    `PolicyConfirmed`: a policy was set or removed for one access selector,
    `(target, selector, operation)`.
    """

    objects = PolicyConfirmationQuerySet.as_manager()
    target = EthereumAddressBinaryField()  # `NULL_ADDRESS` on a fallback policy
    selector = HexV2Field(max_length=4)  # `FALLBACK_SELECTOR` on a fallback policy
    operation = models.PositiveSmallIntegerField(
        choices=[(operation.value, operation.name) for operation in POLICY_OPERATIONS]
    )
    policy = EthereumAddressBinaryField(db_index=True)  # `NULL_ADDRESS` on a removal
    # Opaque to the guard, interpreted by the policy contract. Stored raw and decoded on
    # read, so adding or fixing a decoder needs no backfill, see `policies.decoders`
    data = models.BinaryField(blank=True)

    class Meta:
        indexes = [
            Index(fields=["safe", "-timestamp"]),
            # Latest confirmation per access selector, see `PolicyConfirmationQuerySet.current`
            Index(
                fields=[
                    "safe",
                    "target",
                    "selector",
                    "operation",
                    "-block_number",
                    "-log_index",
                ],
                name="policy_confirmation_access",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ethereum_tx", "log_index"],
                name="unique_policy_confirmation_log",
            )
        ]

    def __str__(self):
        action = "removed for" if self.removed else f"{self.policy} set for"
        return f"{self.safe} - policy {action} {self.target}:{to_0x_hex_str(bytes(self.selector))}"

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> "PolicyConfirmation":
        args = event_data["args"]
        operation = args["operation"]
        if operation not in POLICY_OPERATION_VALUES:
            raise ValueError(
                f"Operation={operation} is not supported by the policy engine"
            )

        return cls(
            **cls._base_parameters_from_decoded_event(event_data),
            target=args["target"],
            selector=HexBytes(args["selector"]),
            operation=operation,
            policy=args["policy"],
            data=HexBytes(args["data"]),
        )

    @property
    def removed(self) -> bool:
        """
        :return: `True` if the policy was removed for this access selector
        """
        return self.policy == NULL_ADDRESS

    @property
    def fallback(self) -> bool:
        """
        :return: `True` if this is the catch-all policy for the operation
        """
        return self.target == NULL_ADDRESS and bytes(self.selector) == FALLBACK_SELECTOR


class PolicyRootEvent(PolicyEngineEvent):
    """Abstract base for the delayed configuration lifecycle events."""

    root = Keccak256Field(db_index=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.safe} - root {to_0x_hex_str(HexBytes(self.root))}"


class PolicyRootStatus(models.TextChoices):
    PENDING = "pending"  # Delay has not elapsed
    READY = "ready"  # Delay elapsed, `applyConfiguration` can be called
    INVALIDATED = "invalidated"  # Cancelled through `invalidateRoot`


class PolicyRootRequestQuerySet(models.QuerySet):
    def with_status(self):
        """
        Annotate `invalidated_at` and `status`.

        A root can be requested, invalidated and requested again, so a request is only
        terminated by the first invalidation that follows it.

        There is no event for a root being applied: `applyConfiguration` emits
        `PolicyConfirmed` per configuration but never names the root, and `MultiSend`
        batching makes recomputing it from those logs ambiguous. So `applied` is not a status.
        """
        invalidations = (
            PolicyRootInvalidation.objects.filter(
                Q(block_number__gt=OuterRef("block_number"))
                | Q(
                    block_number=OuterRef("block_number"),
                    log_index__gt=OuterRef("log_index"),
                ),
                safe=OuterRef("safe"),
                root=OuterRef("root"),
            )
            .order_by("block_number", "log_index")
            .values("timestamp")[:1]
        )
        return self.annotate(
            invalidated_at=Subquery(invalidations),
        ).annotate(
            status=Case(
                When(
                    invalidated_at__isnull=False,
                    then=Value(PolicyRootStatus.INVALIDATED),
                ),
                When(valid_from__gt=Now(), then=Value(PolicyRootStatus.PENDING)),
                default=Value(PolicyRootStatus.READY),
                output_field=models.CharField(choices=PolicyRootStatus.choices),
            )
        )


class PolicyRootRequest(PolicyRootEvent):
    """`RootConfigured`: a delayed configuration was requested for a Safe."""

    objects = PolicyRootRequestQuerySet.as_manager()
    # `block.timestamp + DELAY`, the earliest `applyConfiguration` can be called
    valid_from = models.DateTimeField()

    class Meta:
        indexes = [Index(fields=["safe", "-timestamp"])]
        constraints = [
            models.UniqueConstraint(
                fields=["ethereum_tx", "log_index"],
                name="unique_policy_root_request_log",
            )
        ]

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> "PolicyRootRequest":
        args = event_data["args"]
        return cls(
            **cls._base_parameters_from_decoded_event(event_data),
            root=HexBytes(args["root"]),
            valid_from=datetime.datetime.fromtimestamp(args["timestamp"], datetime.UTC),
        )


class PolicyRootInvalidation(PolicyRootEvent):
    """`RootInvalidated`: a pending configuration request was cancelled."""

    class Meta:
        indexes = [Index(fields=["safe", "-timestamp"])]
        constraints = [
            models.UniqueConstraint(
                fields=["ethereum_tx", "log_index"],
                name="unique_policy_root_invalidation_log",
            )
        ]

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> "PolicyRootInvalidation":
        return cls(
            **cls._base_parameters_from_decoded_event(event_data),
            root=HexBytes(event_data["args"]["root"]),
        )
