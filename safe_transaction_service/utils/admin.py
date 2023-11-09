from django.contrib import admin
from django.contrib.admin.utils import lookup_spawns_duplicates
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.utils.text import smart_split, unescape_string_literal


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


# TODO Use the class in safe-eth-py
class AdvancedAdminSearchMixin:
    """
    Use database indexes when using exact search instead
    of converting everything to text before searching
    """

    def get_search_results(self, request, queryset, search_term):
        """
        Return a tuple containing a queryset to implement the search
        and a boolean indicating if the results may contain duplicates.

        This function was modified from Django original get_search_results
        to allow `exact` search that uses database indexes
        """

        def construct_search(field_name):
            if field_name.startswith("^"):
                return "%s__istartswith" % field_name[1:]
            elif field_name.startswith("=="):
                return "%s__exact" % field_name[2:]
            elif field_name.startswith("="):
                return "%s__iexact" % field_name[1:]
            elif field_name.startswith("@"):
                return "%s__search" % field_name[1:]
            # Use field_name if it includes a lookup.
            opts = queryset.model._meta
            lookup_fields = field_name.split(LOOKUP_SEP)
            # Go through the fields, following all relations.
            prev_field = None
            for path_part in lookup_fields:
                if path_part == "pk":
                    path_part = opts.pk.name
                try:
                    field = opts.get_field(path_part)
                except FieldDoesNotExist:
                    # Use valid query lookups.
                    if prev_field and prev_field.get_lookup(path_part):
                        return field_name
                else:
                    prev_field = field
                    if hasattr(field, "path_infos"):
                        # Update opts to follow the relation.
                        opts = field.path_infos[-1].to_opts
            # Otherwise, use the field with icontains.
            return "%s__icontains" % field_name

        may_have_duplicates = False
        search_fields = self.get_search_fields(request)
        if search_fields and search_term:
            orm_lookups = [
                construct_search(str(search_field)) for search_field in search_fields
            ]
            term_queries = []
            for bit in smart_split(search_term):
                if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
                    bit = unescape_string_literal(bit)

                valid_queries = []
                for orm_lookup in orm_lookups:
                    try:
                        # Check if query is valid (for example, not a number provided for an integer exact query)
                        # This is the main difference comparing to Django official implementation
                        queryset.filter(**{orm_lookup: bit})
                        valid_queries.append((orm_lookup, bit))
                    except (ValueError, ValidationError):
                        pass
                or_queries = models.Q.create(
                    [valid_query for valid_query in valid_queries],
                    connector=models.Q.OR,
                )
                term_queries.append(or_queries)
            queryset = queryset.filter(models.Q.create(term_queries))
            may_have_duplicates |= any(
                lookup_spawns_duplicates(self.opts, search_spec)
                for search_spec in orm_lookups
            )
        return queryset, may_have_duplicates
