from django.contrib import admin

from .models import UserOperation


@admin.register(UserOperation)
class UserOperationAdmin(admin.ModelAdmin):
    list_display = (
        "ethereum_tx_id",
        "sender",
        "nonce",
    )
    search_fields = [
        "==sender",
    ]
    ordering = ["-nonce"]
