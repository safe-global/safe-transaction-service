from django.contrib import admin

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.django.admin import AdvancedAdminSearchMixin

from .models import SafeOperation, UserOperation, UserOperationReceipt


class SafeOperationInline(admin.TabularInline):
    model = SafeOperation


@admin.register(UserOperation)
class UserOperationAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    inlines = [SafeOperationInline]
    list_display = ("hash", "ethereum_tx", "sender", "nonce", "success")
    list_filter = [
        "receipt__success",
    ]
    search_fields = [
        "==ethereum_tx_id",
        "==sender",
    ]
    ordering = ["-nonce"]

    @admin.display(boolean=True, description="Is successful?")
    def success(self, obj: UserOperation) -> bool:
        return obj.receipt.success


# Type for classes with a ForeignKey to UserOperation
ForeignClassToUserOperationType = UserOperationReceipt | SafeOperation


class ForeignClassToUserOperationAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    search_fields = [
        "==user_operation__hash",
        "==user_operation__ethereum_tx_id",
        "==user_operation__sender",
    ]

    @admin.display()
    def ethereum_tx(self, obj: ForeignClassToUserOperationType) -> str:
        return HexBytes(obj.user_operation.ethereum_tx.tx_hash).hex()

    @admin.display()
    def user_operation_hash(self, obj: ForeignClassToUserOperationType) -> str:
        return HexBytes(obj.user_operation.hash).hex()

    @admin.display()
    def user_operation_sender(
        self, obj: ForeignClassToUserOperationType
    ) -> ChecksumAddress:
        return obj.user_operation.sender

    @admin.display()
    def user_operation_nonce(self, obj: ForeignClassToUserOperationType) -> int:
        return obj.user_operation.nonce


@admin.register(UserOperationReceipt)
class UserOperationReceiptAdmin(ForeignClassToUserOperationAdmin):
    list_display = (
        "user_operation_hash",
        "ethereum_tx",
        "user_operation_sender",
        "user_operation_nonce",
        "success",
        "deposited",
    )
    list_filter = [
        "success",
    ]


@admin.register(SafeOperation)
class SafeOperationAdmin(ForeignClassToUserOperationAdmin):
    list_display = (
        "hash",
        "user_operation_hash",
        "ethereum_tx",
        "user_operation_sender",
        "user_operation_nonce",
        "success",
        "module_address",
    )
    list_filter = ["module_address"]
    list_select_related = ["user_operation__receipt"]
    search_fields = ForeignClassToUserOperationAdmin.search_fields + ["==hash"]
    ordering = ["-modified"]

    @admin.display(boolean=True, description="Is successful?")
    def success(self, obj: SafeOperation) -> bool:
        return obj.user_operation.receipt.success
