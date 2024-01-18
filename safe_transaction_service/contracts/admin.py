from django.contrib import admin

from safe_transaction_service.utils.admin import (
    AdvancedAdminSearchMixin,
    HasLogoFilterAdmin,
)

from .models import Contract, ContractAbi
from .tasks import create_or_update_contract_with_metadata_task


@admin.register(ContractAbi)
class ContractAbiAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("pk", "relevance", "description", "abi_functions")
    list_filter = ("relevance",)
    ordering = ["relevance"]
    readonly_fields = ("abi_hash",)
    search_fields = ["description"]

    def abi_functions(self, obj: ContractAbi):
        return obj.abi_functions()


class HasAbiFilter(admin.SimpleListFilter):
    title = "Has ABI"
    parameter_name = "has_abi"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Yes"),
            ("NO", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "NO":
            return queryset.filter(contract_abi=None)
        elif self.value() == "YES":
            return queryset.exclude(contract_abi=None)
        else:
            return queryset


@admin.register(Contract)
class ContractAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    actions = ["find_abi"]
    list_display = (
        "address",
        "name",
        "display_name",
        "has_abi",
        "has_logo",
        "trusted_for_delegate_call",
        "abi_relevance",
        "contract_abi_id",
    )
    list_filter = (HasAbiFilter, HasLogoFilterAdmin, "trusted_for_delegate_call")
    list_select_related = ("contract_abi",)
    ordering = ["address"]
    raw_id_fields = ("contract_abi",)
    search_fields = [
        "==address",
        "name",
        "contract_abi__abi",
        "contract_abi__description",
    ]

    @admin.action(description="Find ABI if missing")
    def find_abi(self, request, queryset):
        for contract_address in queryset.without_metadata().values_list(
            "address", flat=True
        ):
            create_or_update_contract_with_metadata_task.delay(contract_address)

    def abi_relevance(self, obj: Contract):
        if obj.contract_abi_id:
            return obj.contract_abi.relevance

    @admin.display(boolean=True)
    def has_abi(self, obj: Contract) -> bool:
        return obj.contract_abi_id is not None

    @admin.display(boolean=True)
    def has_logo(self, obj: Contract) -> bool:
        return bool(obj.logo)
