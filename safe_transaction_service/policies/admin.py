# SPDX-License-Identifier: FSL-1.1-MIT
import json

from django.contrib import admin
from django.utils.html import format_html

from hexbytes import HexBytes
from safe_eth.eth.django.admin import AdvancedAdminSearchMixin
from safe_eth.util.util import to_0x_hex_str

from .decoders import policy_data_decoder_registry
from .models import (
    PolicyConfirmation,
    PolicyContract,
    PolicyRootInvalidation,
    PolicyRootRequest,
    SafePolicyGuard,
)


@admin.register(SafePolicyGuard)
class SafePolicyGuardAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("address", "initial_block_number", "tx_block_number")
    search_fields = ["==address"]
    ordering = ["tx_block_number"]


@admin.register(PolicyContract)
class PolicyContractAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("name", "address")
    list_filter = ["name"]
    search_fields = ["==address", "name"]
    ordering = ["name"]


class PolicyEngineEventAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_select_related = ["ethereum_tx"]
    search_fields = ["==safe", "==guard", "==ethereum_tx_id"]
    ordering = ["-timestamp", "-log_index"]

    @admin.display(description="Transaction hash")
    def transaction_hash(self, obj: PolicyConfirmation) -> str:
        return to_0x_hex_str(HexBytes(obj.ethereum_tx_id))


@admin.register(PolicyConfirmation)
class PolicyConfirmationAdmin(PolicyEngineEventAdmin):
    list_display = (
        "safe",
        "target",
        "selector_hex",
        "operation",
        "policy",
        "data_hex",
        "block_number",
        "timestamp",
        "transaction_hash",
    )
    list_filter = ["operation"]
    # `data` is a `BinaryField`, so it is not part of the form. Both are computed on read,
    # see `policies.decoders`
    readonly_fields = ["data_hex", "data_decoded"]
    search_fields = PolicyEngineEventAdmin.search_fields + ["==policy", "==target"]

    @admin.display(description="Selector")
    def selector_hex(self, obj: PolicyConfirmation) -> str:
        return to_0x_hex_str(bytes(obj.selector))

    @admin.display(description="Data")
    def data_hex(self, obj: PolicyConfirmation) -> str | None:
        return to_0x_hex_str(HexBytes(obj.data)) if obj.data else None

    @admin.display(description="Data decoded")
    def data_decoded(self, obj: PolicyConfirmation) -> str | None:
        """Same decoding the API exposes, `None` when the policy or the layout is unknown"""
        decoded = policy_data_decoder_registry.decode(obj.policy, obj.data)
        return (
            format_html("<pre>{}</pre>", json.dumps(decoded, indent=2))
            if decoded
            else None
        )


class PolicyRootEventAdmin(PolicyEngineEventAdmin):
    search_fields = PolicyEngineEventAdmin.search_fields + ["==root"]

    @admin.display(description="Root")
    def root_hex(self, obj: PolicyRootRequest | PolicyRootInvalidation) -> str:
        return to_0x_hex_str(HexBytes(obj.root))


@admin.register(PolicyRootRequest)
class PolicyRootRequestAdmin(PolicyRootEventAdmin):
    list_display = (
        "safe",
        "root_hex",
        "valid_from",
        "block_number",
        "timestamp",
        "transaction_hash",
    )


@admin.register(PolicyRootInvalidation)
class PolicyRootInvalidationAdmin(PolicyRootEventAdmin):
    list_display = ("safe", "root_hex", "block_number", "timestamp", "transaction_hash")
