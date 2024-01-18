from typing import Any, Optional

from django import forms
from django.contrib import admin
from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Greatest
from django.db.transaction import atomic
from django.http import HttpRequest

from hexbytes import HexBytes
from rest_framework.authtoken.admin import TokenAdmin

from gnosis.eth import EthereumClientProvider
from gnosis.safe import SafeTx

from safe_transaction_service.utils.admin import AdvancedAdminSearchMixin

from .models import (
    Chain,
    ERC20Transfer,
    ERC721Transfer,
    EthereumBlock,
    EthereumTx,
    IndexingStatus,
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
from .utils import HexField

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
@admin.register(IndexingStatus)
class IndexingStatusAdmin(admin.ModelAdmin):
    class Meta:
        verbose_name_plural = "Indexing Status"

    list_display = (
        "indexing_type",
        "block_number",
    )
    list_filter = ("indexing_type",)
    search_fields = [
        "=block_number",
    ]
    ordering = ["-indexing_type"]


@admin.register(Chain)
class ChainAdmin(admin.ModelAdmin):
    list_display = ("chain_id",)


@admin.register(EthereumBlock)
class EthereumBlockAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "==number",
        "==block_hash",
    ]
    ordering = ["-number"]


class TokenTransferAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
    search_fields = ["==_from", "==to", "==address", "==ethereum_tx__tx_hash"]
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
class EthereumTxAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    inlines = (
        ERC20TransferInline,
        ERC721TransferInline,
        SafeContractInline,
        MultisigTransactionInline,
        MultisigConfirmationInline,
    )
    list_display = ("block_id", "tx_hash", "nonce", "_from", "to")
    list_filter = ("status", "type")
    search_fields = ["==block_id", "==tx_hash", "==_from", "==to"]
    ordering = ["-block_id"]
    raw_id_fields = ("block",)


@admin.register(InternalTx)
class InternalTxAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "-pk",
    ]
    raw_id_fields = ("ethereum_tx",)
    search_fields = [
        "==block_number",
        "==_from",
        "==to",
        "==ethereum_tx__tx_hash",
        "==contract_address",
    ]


class InternalTxDecodedOfficialListFilter(admin.SimpleListFilter):
    title = "Official Safes"
    parameter_name = "official_safes"

    def lookups(self, request, model_admin):
        return (("YES", "Yes"),)

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.filter(
                Q(
                    Exists(
                        SafeContract.objects.filter(
                            address=OuterRef("internal_tx___from")
                        )
                    )
                )  # Just Safes indexed
                | Q(function_name="setup")  # Safes pending to be indexed
            )


@admin.register(InternalTxDecoded)
class InternalTxDecodedAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "-internal_tx_id",
    ]
    raw_id_fields = ("internal_tx",)
    search_fields = [
        "==function_name",
        "==internal_tx__to",
        "==internal_tx___from",
        "==internal_tx__ethereum_tx__tx_hash",
        "==internal_tx__block_number",
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
class MultisigConfirmationAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "==multisig_transaction__safe",
        "==ethereum_tx__tx_hash",
        "==multisig_transaction_hash",
        "==owner",
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


class MultisigTransactionDataListFilter(admin.SimpleListFilter):
    title = "Has data"
    parameter_name = "has_data"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Transaction has data"),
            ("NO", "Transaction data is empty"),
        )

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.with_data()
        elif self.value() == "NO":
            return queryset.without_data()


class MultisigTransactionAdminForm(forms.ModelForm):
    data = HexField(required=False)


@admin.register(MultisigTransaction)
class MultisigTransactionAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    date_hierarchy = "created"
    form = MultisigTransactionAdminForm
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
    )
    list_filter = (
        MultisigTransactionExecutedListFilter,
        MultisigTransactionDataListFilter,
        "operation",
        "failed",
        "trusted",
    )
    list_select_related = ("ethereum_tx",)
    ordering = ["-created"]
    raw_id_fields = ("ethereum_tx",)
    readonly_fields = ("safe_tx_hash",)
    search_fields = ["==ethereum_tx__tx_hash", "==safe", "==to", "==safe_tx_hash"]

    @admin.display(boolean=True)
    def executed(self, obj: MultisigTransaction):
        return obj.executed

    @admin.display(boolean=True)
    def successful(self, obj: MultisigTransaction):
        return not obj.failed

    def save_model(
        self, request: HttpRequest, obj: MultisigTransaction, form: Any, change: Any
    ) -> None:
        if obj.safe_tx_hash:
            # When modifying the primary key, another instance will be created so we delete the previous one if not executed
            MultisigTransaction.objects.not_executed().filter(
                safe_tx_hash=obj.safe_tx_hash
            ).delete()

        # Calculate new tx hash
        # All the numbers are decimals, they need to be parsed as integers for SafeTx
        safe_tx = SafeTx(
            EthereumClientProvider(),
            obj.safe,
            obj.to,
            int(obj.value),
            obj.data,
            int(obj.operation),
            int(obj.safe_tx_gas),
            int(obj.base_gas),
            int(obj.gas_price),
            obj.gas_token,
            obj.refund_receiver,
            obj.signatures,
            safe_nonce=int(obj.nonce),
        )
        obj.safe_tx_hash = safe_tx.safe_tx_hash
        return super().save_model(request, obj, form, change)


@admin.register(ModuleTransaction)
class ModuleTransactionAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
    search_fields = ["==safe", "==module", "==to"]

    def data_hex(self, o: ModuleTransaction):
        return HexBytes(o.data.tobytes()).hex() if o.data else None

    def tx_hash(self, o: ModuleTransaction):
        return o.internal_tx.ethereum_tx_id


class MonitoredAddressAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    actions = ["reindex", "reindex_last_day", "reindex_last_week", "reindex_last_month"]
    list_display = ("address", "initial_block_number", "tx_block_number")
    search_fields = ["==address"]

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
class SafeContractAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    inlines = (SafeContractDelegateInline,)
    list_display = (
        "created_block_number",
        "address",
        "ethereum_tx_id",
    )
    list_filter = (SafeContractERC20ListFilter,)
    list_select_related = ("ethereum_tx",)
    ordering = ["-ethereum_tx__block_id"]
    raw_id_fields = ("ethereum_tx",)
    search_fields = [
        "==address",
        "==ethereum_tx__tx_hash",
        "==ethereum_tx__block_id",
    ]


@admin.register(SafeContractDelegate)
class SafeContractDelegateAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("safe_contract", "read", "write", "delegate", "delegator")
    list_filter = ("read", "write")
    ordering = ["safe_contract_id"]
    raw_id_fields = ("safe_contract",)
    search_fields = ["==safe_contract__address", "==delegate", "==delegator"]


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
class SafeLastStatusAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "==address",
        "owners__icontains",
        "==internal_tx__ethereum_tx__tx_hash",
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
class WebHookAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
    search_fields = ["==address", "==url"]
