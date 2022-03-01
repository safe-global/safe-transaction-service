from django.contrib import admin

from safe_transaction_service.utils.admin import BinarySearchAdmin, HasLogoFilterAdmin

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
        "copy_price",
    )
    list_filter = ("trusted", "spam", "events_bugged", "decimals", HasLogoFilterAdmin)
    ordering = ("address",)
    search_fields = ["=address", "symbol", "name", "=copy_price"]
