from django.contrib import admin

from gnosis.eth.django.admin import BinarySearchAdmin

from safe_transaction_service.utils.admin import HasLogoFilterAdmin

from .models import SafeMessage, SafeMessageConfirmation


@admin.register(SafeMessage)
class SafeMessageAdmin(BinarySearchAdmin):
    date_hierarchy = "created"
    list_display = ("safe", "message_hash", "proposed_by", "description")
    ordering = ["-created"]
    readonly_fields = ("message_hash",)
    search_fields = ["safe", "message_hash", "proposed_by", "description"]


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
        "safe_message__safe",
        "name",
        "contract_abi__abi",
        "contract_abi__description",
    ]

    def abi_relevance(self, obj: Contract):
        if obj.contract_abi_id:
            return obj.contract_abi.relevance

    @admin.display(boolean=True)
    def has_abi(self, obj: Contract) -> bool:
        return obj.contract_abi_id is not None

    @admin.display(boolean=True)
    def has_logo(self, obj: Contract) -> bool:
        return bool(obj.logo)
