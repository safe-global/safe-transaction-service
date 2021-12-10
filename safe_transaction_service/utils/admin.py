from typing import Tuple

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest


class BinarySearchAdmin(admin.ModelAdmin):
    def get_search_results(
        self, request: HttpRequest, queryset: QuerySet, search_term: str
    ) -> Tuple[QuerySet, bool]:
        queryset, may_have_duplicates = super().get_search_results(
            request, queryset, search_term
        )
        if search_term:
            for search_field in self.get_search_fields(request):
                try:
                    if search_field.startswith("="):
                        may_have_duplicates = True
                        queryset |= self.model.objects.filter(
                            **{search_field[1:]: search_term}
                        )
                    elif search_field.endswith("__icontains"):
                        may_have_duplicates = True
                        queryset |= self.model.objects.filter(
                            **{
                                search_field.replace("__icontains", "__contains"): [
                                    search_term
                                ]
                            }
                        )
                except ValidationError:
                    pass
        return queryset, may_have_duplicates
