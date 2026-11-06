# SPDX-License-Identifier: FSL-1.1-MIT
from django.contrib import admin

from safe_transaction_service.utils.admin import (
    AdvancedAdminSearchMixin,
    HasLogoFilterAdmin,
)

from .models import Token, TokenList, TokenNotValid


@admin.register(Token)
class TokenAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = (
        "address",
        "trusted",
        "trusted_admin",
        "spam",
        "events_bugged",
        "name",
        "symbol",
        "decimals",
        "copy_price",
    )
    list_filter = (
        "trusted",
        "trusted_admin",
        "spam",
        "events_bugged",
        "decimals",
        HasLogoFilterAdmin,
    )
    # `trusted` is owned by `update_token_info_from_token_list_task`, curation must go
    # through `trusted_admin` so it is not wiped on the next run
    readonly_fields = ("trusted",)
    ordering = ("address",)
    search_fields = ["==address", "symbol", "name", "==copy_price"]


@admin.register(TokenList)
class TokenListAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "url",
        "description",
    )
    ordering = ("pk",)
    search_fields = ["url", "description"]


@admin.register(TokenNotValid)
class TokenNotValidAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("address",)
    ordering = ("address",)
    search_fields = ["==address"]
