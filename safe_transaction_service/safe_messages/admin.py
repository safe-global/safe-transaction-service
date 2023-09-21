from django.contrib import admin

from gnosis.eth.django.admin import BinarySearchAdmin

from .models import SafeMessage, SafeMessageConfirmation


@admin.register(SafeMessage)
class SafeMessageAdmin(BinarySearchAdmin):
    date_hierarchy = "created"
    list_display = ("safe", "message_hash", "proposed_by", "message")
    ordering = ["-created"]
    readonly_fields = ("message_hash",)
    search_fields = ["=safe", "=message_hash", "=proposed_by", "message"]


@admin.register(SafeMessageConfirmation)
class SafeMessageConfirmationAdmin(BinarySearchAdmin):
    date_hierarchy = "created"
    list_display = (
        "safe_message",
        "owner",
        "signature_type",
    )
    list_filter = ("signature_type",)
    list_select_related = ("safe_message",)
    ordering = ["-created"]
    search_fields = [
        "=safe_message__safe",
        "=owner",
        "safe_message__description",
    ]
