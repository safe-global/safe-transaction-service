from django.contrib import admin

from safe_transaction_service.utils.admin import BinarySearchAdmin

from .models import Token


@admin.register(Token)
class TokenAdmin(BinarySearchAdmin):
    list_display = (
        "address",
        "trusted",
        "spam",
        "events_bugged",
        "name",
        "symbol",
        "decimals",
    )
    list_filter = ("trusted", "spam", "events_bugged", "decimals")
    ordering = ("name",)
    search_fields = ["=address", "symbol", "name"]
