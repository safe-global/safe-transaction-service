from django.contrib import admin

from .models import Contract, ContractAbi


@admin.register(ContractAbi)
class ContractAbiAdmin(admin.ModelAdmin):
    list_display = ('pk', 'relevance', 'description', 'abi_functions')
    list_filter = ('relevance',)
    ordering = ['relevance']
    search_fields = ['description']

    def abi_functions(self, obj: ContractAbi):
        return obj.abi_functions()


class HasAbiFilter(admin.SimpleListFilter):
    title = 'Has ABI'
    parameter_name = 'has_abi'

    def lookups(self, request, model_admin):
        return (
            ('YES', 'Yes'),
            ('NO', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'NO':
            return queryset.filter(contract_abi=None)
        elif self.value() == 'YES':
            return queryset.exclude(contract_abi=None)
        else:
            return queryset


class HasLogoFilter(admin.SimpleListFilter):
    title = 'Has Logo'
    parameter_name = 'has_logo'

    def lookups(self, request, model_admin):
        return (
            ('YES', 'Yes'),
            ('NO', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'NO':
            return queryset.without_logo()
        elif self.value() == 'YES':
            return queryset.with_logo()
        else:
            return queryset


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('address', 'name', 'display_name', 'has_abi', 'has_logo', 'abi_relevance', 'contract_abi_id')
    list_filter = (HasAbiFilter, HasLogoFilter)
    list_select_related = ('contract_abi',)
    ordering = ['address']
    raw_id_fields = ('contract_abi',)
    search_fields = ['address', 'name', 'contract_abi__abi', 'contract_abi__description']

    def abi_relevance(self, obj: Contract):
        if obj.contract_abi_id:
            return obj.contract_abi.relevance

    def has_abi(self, obj: Contract) -> bool:
        return obj.contract_abi_id is not None
    has_abi.boolean = True

    def has_logo(self, obj: Contract) -> bool:
        return bool(obj.logo)
    has_logo.boolean = True
