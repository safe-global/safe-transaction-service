from django.contrib import admin


class HasLogoFilterAdmin(admin.SimpleListFilter):
    title = "Has Logo"
    parameter_name = "has_logo"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Yes"),
            ("NO", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "NO":
            return queryset.without_logo()
        elif self.value() == "YES":
            return queryset.with_logo()
        else:
            return queryset
