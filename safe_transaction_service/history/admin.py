from typing import Optional

from django.contrib import admin
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.db.transaction import atomic

from hexbytes import HexBytes
from rest_framework.authtoken.admin import TokenAdmin

from gnosis.eth import EthereumClientProvider

from safe_transaction_service.utils.admin import BinarySearchAdmin

from .models import (
    ERC20Transfer,
    ERC721Transfer,
    EthereumBlock,
    EthereumTx,
    InternalTx,
    InternalTxDecoded,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    ProxyFactory,
    SafeContract,
    SafeContractDelegate,
    SafeLastStatus,
    SafeMasterCopy,
    SafeStatus,
    WebHook,
)
from .services import IndexServiceProvider

# By default, TokenAdmin doesn't allow key edition
# IFF you have a service that requests from multiple safe-transaction-service
# you might want to share that key for convenience between instances.
TokenAdmin.fields = (
    "user",
    "key",
)


# Inline objects ------------------------------
class ERC20TransferInline(admin.TabularInline):
    model = ERC20Transfer
    raw_id_fields = ("ethereum_tx",)


class ERC721TransferInline(admin.TabularInline):
    model = ERC721Transfer
    raw_id_fields = ("ethereum_tx",)


class EthereumTxInline(admin.TabularInline):
    model = EthereumTx
    raw_id_fields = ("block",)


class InternalTxDecodedInline(admin.TabularInline):
    model = InternalTxDecoded
    raw_id_fields = ("internal_tx",)


class MultisigTransactionInline(admin.TabularInline):
    model = MultisigTransaction
    raw_id_fields = ("ethereum_tx",)


class MultisigConfirmationInline(admin.TabularInline):
    model = MultisigConfirmation
    raw_id_fields = ("ethereum_tx", "multisig_transaction")


class SafeContractInline(admin.TabularInline):
    model = SafeContract
    raw_id_fields = ("ethereum_tx",)


class SafeContractDelegateInline(admin.TabularInline):
    model = SafeContractDelegate
    raw_id_fields = ("safe_contract",)


# Admin models ------------------------------
@admin.register(EthereumBlock)
class EthereumBlockAdmin(admin.ModelAdmin):
    date_hierarchy = "timestamp"
    inlines = (EthereumTxInline,)
    list_display = (
        "number",
        "timestamp",
        "confirmed",
        "gas_limit",
        "gas_used",
        "block_hash",
    )
    list_filter = ("confirmed",)
    search_fields = [
        "number",
        "=block_hash",
    ]
    ordering = ["-number"]


class TokenTransferAdmin(BinarySearchAdmin):
    date_hierarchy = "timestamp"
    list_display = (
        "timestamp",
        "block_number",
        "log_index",
        "address",
        "_from",
        "to",
        "value",
        "ethereum_tx_id",
    )
    list_select_related = ("ethereum_tx",)
    ordering = ["-timestamp"]
    search_fields = ["=_from", "=to", "=address", "=ethereum_tx__tx_hash"]
    raw_id_fields = ("ethereum_tx",)


@admin.register(ERC20Transfer)
class ERC20TransferAdmin(TokenTransferAdmin):
    actions = ["to_erc721"]

    @admin.action(description="Convert to ERC721 Transfer")
    @atomic
    def to_erc721(self, request, queryset):
        for element in queryset:
            element.to_erc721_transfer().save()
        queryset.delete()


@admin.register(ERC721Transfer)
class ERC721TransferAdmin(TokenTransferAdmin):
    actions = ["to_erc20"]

    @admin.action(description="Convert to ERC20 Transfer")
    @atomic
    def to_erc20(self, request, queryset):
        for element in queryset:
            element.to_erc20_transfer().save()
        queryset.delete()


@admin.register(EthereumTx)
class EthereumTxAdmin(BinarySearchAdmin):
    inlines = (
        ERC20TransferInline,
        ERC721TransferInline,
        SafeContractInline,
        MultisigTransactionInline,
        MultisigConfirmationInline,
    )
    list_display = ("block_id", "tx_hash", "nonce", "_from", "to")
    list_filter = ("status", "type")
    search_fields = ["=tx_hash", "=_from", "=to"]
    ordering = ["-block_id"]
    raw_id_fields = ("block",)


@admin.register(InternalTx)
class InternalTxAdmin(BinarySearchAdmin):
    date_hierarchy = "timestamp"
    inlines = (InternalTxDecodedInline,)
    list_display = (
        "timestamp",
        "block_number",
        "call_type",
        "ethereum_tx_id",
        "_from",
        "to",
        "value",
        "trace_address",
    )
    list_filter = ("tx_type", "call_type")
    list_select_related = ("ethereum_tx",)
    ordering = [
        "-block_number",
        "-ethereum_tx__transaction_index",
        "-trace_address",
    ]
    raw_id_fields = ("ethereum_tx",)
    search_fields = [
        "block_number",
        "=_from",
        "=to",
        "=ethereum_tx__tx_hash",
        "=contract_address",
    ]


class InternalTxDecodedOfficialListFilter(admin.SimpleListFilter):
    title = "Gnosis official Safes"
    parameter_name = "official_safes"

    def lookups(self, request, model_admin):
        return (("YES", "Yes"),)

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.filter(
                Q(
                    internal_tx___from__in=SafeContract.objects.values("address")
                )  # Just Safes indexed
                | Q(function_name="setup")  # Safes pending to be indexed
            )


@admin.register(InternalTxDecoded)
class InternalTxDecodedAdmin(BinarySearchAdmin):
    actions = ["process_again"]
    list_display = (
        "block_number",
        "processed",
        "internal_tx_id",
        "tx_hash",
        "address",
        "function_name",
        "arguments",
    )
    list_filter = ("function_name", "processed", InternalTxDecodedOfficialListFilter)
    list_select_related = ("internal_tx__ethereum_tx",)
    ordering = [
        "-internal_tx__block_number",
        "-internal_tx__ethereum_tx__transaction_index",
        "-internal_tx__trace_address",
    ]
    raw_id_fields = ("internal_tx",)
    search_fields = [
        "function_name",
        "arguments",
        "=internal_tx__to",
        "=internal_tx___from",
        "=internal_tx__ethereum_tx__tx_hash",
        "=internal_tx__block_number",
    ]

    @admin.action(description="Process internal tx again")
    def process_again(self, request, queryset):
        queryset.filter(processed=True).update(processed=False)


class MultisigConfirmationListFilter(admin.SimpleListFilter):
    title = "Has multisig transaction"
    parameter_name = "has_multisig_tx"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Yes"),
            ("NO", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.exclude(multisig_transaction=None)
        elif self.value() == "NO":
            return queryset.filter(multisig_transaction=None)


@admin.register(MultisigConfirmation)
class MultisigConfirmationAdmin(BinarySearchAdmin):
    list_display = (
        "block_number",
        "multisig_transaction_hash",
        "has_multisig_tx",
        "ethereum_tx_id",
        "signature_type",
        "owner",
    )
    list_filter = (MultisigConfirmationListFilter, "signature_type")
    list_select_related = ("ethereum_tx",)
    ordering = ["-created"]
    raw_id_fields = ("ethereum_tx", "multisig_transaction")
    search_fields = [
        "=multisig_transaction__safe",
        "=ethereum_tx__tx_hash",
        "=multisig_transaction_hash",
        "=owner",
    ]

    @admin.display()
    def block_number(self, obj: MultisigConfirmation) -> Optional[int]:
        if obj.ethereum_tx:
            return obj.ethereum_tx.block_id

    @admin.display(boolean=True)
    def has_multisig_tx(self, obj: MultisigConfirmation) -> bool:
        return bool(obj.multisig_transaction_id)


class MultisigTransactionExecutedListFilter(admin.SimpleListFilter):
    title = "Executed"
    parameter_name = "executed"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Transaction executed (mined)"),
            ("NO", "Transaction not executed"),
        )

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.executed()
        elif self.value() == "NO":
            return queryset.not_executed()


@admin.register(MultisigTransaction)
class MultisigTransactionAdmin(BinarySearchAdmin):
    date_hierarchy = "created"
    inlines = (MultisigConfirmationInline,)
    list_display = (
        "created",
        "nonce",
        "safe",
        "executed",
        "successful",
        "safe_tx_hash",
        "ethereum_tx_id",
        "to",
        "value",
        "data",
    )
    list_filter = (MultisigTransactionExecutedListFilter, "failed", "trusted")
    list_select_related = ("ethereum_tx",)
    ordering = ["-created"]
    raw_id_fields = ("ethereum_tx",)
    search_fields = ["=ethereum_tx__tx_hash", "=safe", "=to", "=safe_tx_hash"]

    @admin.display(boolean=True)
    def executed(self, obj: MultisigTransaction):
        return obj.executed

    @admin.display(boolean=True)
    def successful(self, obj: MultisigTransaction):
        return not obj.failed


@admin.register(ModuleTransaction)
class ModuleTransactionAdmin(BinarySearchAdmin):
    date_hierarchy = "created"
    list_display = (
        "created",
        "failed",
        "safe",
        "tx_hash",
        "module",
        "to",
        "operation",
        "value",
        "data_hex",
    )
    list_filter = ("failed", "operation", "module")
    list_select_related = ("internal_tx",)
    ordering = ["-created"]
    raw_id_fields = ("internal_tx",)
    search_fields = ["=safe", "=module", "=to"]

    def data_hex(self, o: ModuleTransaction):
        return HexBytes(o.data.tobytes()).hex() if o.data else None

    def tx_hash(self, o: ModuleTransaction):
        return o.internal_tx.ethereum_tx_id


class MonitoredAddressAdmin(BinarySearchAdmin):
    actions = ["reindex", "reindex_last_day", "reindex_last_week", "reindex_last_month"]
    list_display = ("address", "initial_block_number", "tx_block_number")
    readonly_fields = ["initial_block_number"]
    search_fields = ["=address"]

    @admin.action(description="Reindex from initial block")
    def reindex(self, request, queryset):
        queryset.update(tx_block_number=F("initial_block_number"))

    @admin.action(description="Reindex last 24 hours")
    def reindex_last_day(self, request, queryset):
        queryset.update(
            tx_block_number=Greatest(
                F("tx_block_number") - 6000, F("initial_block_number")
            )
        )

    @admin.action(description="Reindex last week")
    def reindex_last_week(self, request, queryset):
        queryset.update(
            tx_block_number=Greatest(
                F("tx_block_number") - 42000, F("initial_block_number")
            )
        )

    @admin.action(description="Reindex last month")
    def reindex_last_month(self, request, queryset):
        queryset.update(
            tx_block_number=Greatest(
                F("tx_block_number") - 200000, F("initial_block_number")
            )
        )


@admin.register(SafeMasterCopy)
class SafeMasterCopyAdmin(MonitoredAddressAdmin):
    list_display = (
        "address",
        "initial_block_number",
        "tx_block_number",
        "version",
        "l2",
        "deployer",
    )
    list_filter = ("deployer",)


@admin.register(ProxyFactory)
class ProxyFactoryAdmin(MonitoredAddressAdmin):
    pass


class SafeContractERC20ListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = "ERC20 Indexation"

    # Parameter for the filter that will be used in the URL query.
    parameter_name = "erc20_indexation"

    def lookups(self, request, model_admin):
        return (
            ("YES", "ERC20 Indexation updated"),
            ("NO", "ERC20 Indexation not updated"),
        )

    def queryset(self, request, queryset):
        current_block_number = EthereumClientProvider().current_block_number
        condition = {"erc20_block_number__gte": current_block_number - 200}
        if self.value() == "YES":
            return queryset.filter(**condition)
        elif self.value() == "NO":
            return queryset.exclude(**condition)


@admin.register(SafeContract)
class SafeContractAdmin(BinarySearchAdmin):
    actions = ["reindex", "reindex_last_day", "reindex_last_month"]
    inlines = (SafeContractDelegateInline,)
    list_display = (
        "created_block_number",
        "address",
        "ethereum_tx_id",
        "erc20_block_number",
    )
    list_filter = (SafeContractERC20ListFilter,)
    list_select_related = ("ethereum_tx",)
    ordering = ["-ethereum_tx__block_id"]
    raw_id_fields = ("ethereum_tx",)
    search_fields = ["=address", "=ethereum_tx__tx_hash"]

    @admin.action(description="Reindex from initial block")
    def reindex(self, request, queryset):
        queryset.exclude(ethereum_tx=None).update(
            erc20_block_number=F("ethereum_tx__block_id")
        )

    @admin.action(description="Reindex last 24 hours")
    def reindex_last_day(self, request, queryset):
        queryset.update(erc20_block_number=Greatest(F("erc20_block_number") - 6000, 0))

    @admin.action(description="Reindex last month")
    def reindex_last_month(self, request, queryset):
        queryset.update(
            erc20_block_number=Greatest(F("erc20_block_number") - 200000, 0)
        )


@admin.register(SafeContractDelegate)
class SafeContractDelegateAdmin(BinarySearchAdmin):
    list_display = ("safe_contract", "read", "write", "delegate", "delegator")
    list_filter = ("read", "write")
    ordering = ["safe_contract_id"]
    raw_id_fields = ("safe_contract",)
    search_fields = ["=safe_contract__address", "=delegate", "=delegator"]


class SafeStatusModulesListFilter(admin.SimpleListFilter):
    title = "Modules enabled in Safe"
    parameter_name = "enabled_modules"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Yes"),
            ("NO", "No"),
        )

    def queryset(self, request, queryset):
        parameters = {"enabled_modules__len__gt": 0}
        if self.value() == "YES":
            return queryset.filter(**parameters)
        elif self.value() == "NO":
            return queryset.exclude(**parameters)


@admin.register(SafeLastStatus)
class SafeLastStatusAdmin(BinarySearchAdmin):
    actions = ["remove_and_index"]
    fields = (
        "internal_tx",
        "address",
        "owners",
        "threshold",
        "nonce",
        "master_copy",
        "fallback_handler",
        "enabled_modules",
        "function_name",
        "arguments",
    )
    readonly_fields = ("function_name", "arguments")
    list_display = (
        "block_number",
        "internal_tx_id",
        "function_name",
        "address",
        "owners",
        "threshold",
        "nonce",
        "master_copy",
        "fallback_handler",
        "guard",
        "enabled_modules",
    )
    list_filter = (
        "threshold",
        "master_copy",
        "fallback_handler",
        "guard",
        SafeStatusModulesListFilter,
    )
    list_select_related = ("internal_tx__ethereum_tx", "internal_tx__decoded_tx")
    ordering = ["-internal_tx__ethereum_tx__block_id", "-internal_tx_id"]
    raw_id_fields = ("internal_tx",)
    search_fields = [
        "=address",
        "owners__icontains",
        "=internal_tx__ethereum_tx__tx_hash",
        "enabled_modules__icontains",
    ]

    def function_name(self, obj: SafeStatus) -> str:
        return obj.internal_tx.decoded_tx.function_name

    def arguments(self, obj: SafeStatus) -> str:
        return obj.internal_tx.decoded_tx.arguments

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Remove and process transactions again")
    def remove_and_index(self, request, queryset):
        safe_addresses = list(queryset.distinct().values_list("address", flat=True))
        IndexServiceProvider().reprocess_addresses(safe_addresses)


@admin.register(SafeStatus)
class SafeStatusAdmin(SafeLastStatusAdmin):
    pass


@admin.register(WebHook)
class WebHookAdmin(BinarySearchAdmin):
    list_display = (
        "pk",
        "url",
        "authorization",
        "address",
        "pending_multisig_transaction",
        "new_confirmation",
        "new_executed_multisig_transaction",
        "new_incoming_transaction",
        "new_safe",
        "new_module_transaction",
        "new_outgoing_transaction",
    )
    list_filter = (
        "pending_multisig_transaction",
        "new_confirmation",
        "new_executed_multisig_transaction",
        "new_incoming_transaction",
        "new_safe",
        "new_module_transaction",
        "new_outgoing_transaction",
    )
    ordering = ["-pk"]
    search_fields = ["=address", "url"]
