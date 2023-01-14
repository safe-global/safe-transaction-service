from django.contrib import admin

from gnosis.eth.django.admin import BinarySearchAdmin

from safe_transaction_service.utils.admin import HasLogoFilterAdmin

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
