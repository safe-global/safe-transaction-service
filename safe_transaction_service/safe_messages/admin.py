from django.contrib import admin

from safe_transaction_service.utils.admin import AdvancedAdminSearchMixin

from .models import SafeMessage, SafeMessageConfirmation


@admin.register(SafeMessage)
class SafeMessageAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = ("safe", "message_hash", "proposed_by", "message")
    ordering = ["-created"]
    readonly_fields = ("message_hash",)
    search_fields = ["==safe", "==message_hash", "==proposed_by", "message"]


@admin.register(SafeMessageConfirmation)
class SafeMessageConfirmationAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
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
        "==safe_message__safe",
        "==owner",
    ]
