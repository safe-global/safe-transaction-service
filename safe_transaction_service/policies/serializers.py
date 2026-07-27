# SPDX-License-Identifier: FSL-1.1-MIT
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from safe_eth.eth.django import serializers as eth_serializers

from .decoders import policy_data_decoder_registry
from .models import PolicyConfirmation, PolicyRootRequest, PolicyRootStatus


class PolicyDataDecodedResponseSerializer(serializers.Serializer):
    """Documents the `data_decoded` payload, the parameters shape is policy specific."""

    policy_name = serializers.CharField()
    parameters = serializers.DictField()


class PolicyConfirmationResponseSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    guard = eth_serializers.EthereumAddressField(
        help_text="`SafePolicyGuard` that emitted the event"
    )
    target = eth_serializers.EthereumAddressField(
        help_text="Contract the policy applies to, empty address on a fallback policy"
    )
    selector = eth_serializers.HexadecimalField(
        help_text="Function selector the policy applies to, `0x00000000` on a fallback policy"
    )
    operation = serializers.IntegerField(help_text="0 `CALL`, 1 `DELEGATE_CALL`")
    policy = eth_serializers.EthereumAddressField(
        help_text="Policy enforcing the access, empty address when the policy was removed"
    )
    removed = serializers.BooleanField(
        help_text="`true` if the policy was removed for this target, selector and operation"
    )
    fallback = serializers.BooleanField(
        help_text="`true` if the policy is the catch-all for the operation"
    )
    data = eth_serializers.HexadecimalField(
        allow_null=True,
        allow_blank=True,
        help_text="Configuration the policy was set up with, interpreted by the policy",
    )
    data_decoded = serializers.SerializerMethodField()
    transaction_hash = eth_serializers.HexadecimalField(source="ethereum_tx_id")
    block_number = serializers.IntegerField()
    log_index = serializers.IntegerField()
    timestamp = serializers.DateTimeField()

    @extend_schema_field(PolicyDataDecodedResponseSerializer(allow_null=True))
    def get_data_decoded(self, obj: PolicyConfirmation) -> dict[str, Any] | None:
        return policy_data_decoder_registry.decode(obj.policy, obj.data)


class PolicyRootRequestResponseSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    guard = eth_serializers.EthereumAddressField(
        help_text="`SafePolicyGuard` that emitted the event"
    )
    root = eth_serializers.HexadecimalField(
        help_text="`keccak256(abi.encode(configurations))` of the requested configuration"
    )
    valid_from = serializers.DateTimeField(
        help_text="Earliest time `applyConfiguration` can be called"
    )
    status = serializers.ChoiceField(choices=PolicyRootStatus.choices)
    invalidated_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the request was cancelled through `invalidateRoot`",
    )
    transaction_hash = eth_serializers.HexadecimalField(source="ethereum_tx_id")
    block_number = serializers.IntegerField()
    log_index = serializers.IntegerField()
    timestamp = serializers.DateTimeField(help_text="When the request was made")

    def to_representation(self, instance: PolicyRootRequest):
        assert hasattr(instance, "status"), (
            "`status` and `invalidated_at` are annotations, "
            "the queryset must be built with `with_status()`"
        )
        return super().to_representation(instance)
