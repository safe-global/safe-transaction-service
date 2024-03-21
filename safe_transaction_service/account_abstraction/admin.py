from django.contrib import admin

from eth_typing import ChecksumAddress, HexStr

from safe_transaction_service.history import models as history_models

from .models import SafeOperation, UserOperation, UserOperationReceipt


@admin.register(UserOperation)
class UserOperationAdmin(admin.ModelAdmin):
    list_display = ("hash", "ethereum_tx", "sender", "nonce", "success")
    list_filter = [
        "receipt__success",
    ]
    search_fields = [
        "==sender",
    ]
    ordering = ["-nonce"]

    @admin.display(boolean=True, description="Is successful?")
    def success(self, obj: UserOperation) -> bool:
        return obj.receipt.success


@admin.register(UserOperationReceipt)
class UserOperationReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "user_operation_hash",
        "user_operation_sender",
        "user_operation_nonce",
        "success",
        "deposited",
    )
    list_filter = [
        "success",
    ]
    search_fields = [
        "==user_operation__sender",
    ]

    @admin.display()
    def user_operation_hash(self, obj: UserOperationReceipt) -> HexStr:
        return obj.user_operation.hash

    @admin.display()
    def user_operation_sender(self, obj: UserOperationReceipt) -> ChecksumAddress:
        return obj.user_operation.sender

    @admin.display()
    def user_operation_nonce(self, obj: UserOperationReceipt) -> int:
        return obj.user_operation.nonce


@admin.register(SafeOperation)
class SafeOperationAdmin(admin.ModelAdmin):
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
    search_fields = [
        "==user_operation__sender",
    ]
    ordering = ["-modified"]

    @admin.display()
    def ethereum_tx(self, obj: SafeOperation) -> history_models.EthereumTx:
        return obj.user_operation.ethereum_tx

    @admin.display()
    def user_operation_hash(self, obj: SafeOperation) -> HexStr:
        return obj.user_operation.hash

    @admin.display()
    def user_operation_sender(self, obj: SafeOperation) -> ChecksumAddress:
        return obj.user_operation.sender

    @admin.display()
    def user_operation_nonce(self, obj: SafeOperation) -> int:
        return obj.user_operation.nonce

    @admin.display(boolean=True, description="Is successful?")
    def success(self, obj: SafeOperation) -> bool:
        return obj.user_operation.receipt.success
