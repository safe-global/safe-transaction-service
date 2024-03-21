from django.contrib import admin

from .models import SafeOperation, UserOperation, UserOperationReceipt


@admin.register(UserOperation)
class UserOperationAdmin(admin.ModelAdmin):
    list_display = ("hash", "ethereum_tx_id", "sender", "nonce", "receipt__success")
    list_filter = [
        "receipt__success",
    ]
    search_fields = [
        "==sender",
    ]
    ordering = ["-nonce"]


@admin.register(UserOperationReceipt)
class UserOperationReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "user_operation__hash",
        "user_operation__sender",
        "user_operation__nonce",
        "success",
        "deposited",
    )
    list_filter = [
        "success",
    ]
    search_fields = [
        "==sender",
    ]
    ordering = ["-nonce"]


@admin.register(SafeOperation)
class SafeOperationAdmin(admin.ModelAdmin):
    list_display = (
        "hash",
        "user_operation__hash",
        "ethereum_tx_id",
        "user_operation__sender",
        "user_operation__nonce",
        "module_address",
    )
    list_filter = ["module_address"]
    search_fields = [
        "==sender",
    ]
    ordering = ["-nonce"]
