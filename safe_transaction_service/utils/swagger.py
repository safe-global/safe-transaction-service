import os
import re

from drf_spectacular.drainage import add_trace_message, error, get_override, warn
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import camelize_operation
from drf_spectacular.settings import spectacular_settings


class IgnoreVersionSchemaGenerator(SchemaGenerator):

    def parse(self, input_request, public):
        """Iterate endpoints generating per method path operations."""
        result = {}
        self._initialise_endpoints()
        endpoints = self._get_paths_and_endpoints()

        if spectacular_settings.SCHEMA_PATH_PREFIX is None:
            # estimate common path prefix if none was given. only use it if we encountered more
            # than one view to prevent emission of erroneous and unnecessary fallback names.
            non_trivial_prefix = (
                len(set([view.__class__ for _, _, _, view in endpoints])) > 1
            )
            if non_trivial_prefix:
                path_prefix = os.path.commonpath([path for path, _, _, _ in endpoints])
                path_prefix = re.escape(
                    path_prefix
                )  # guard for RE special chars in path
            else:
                path_prefix = "/"
        else:
            path_prefix = spectacular_settings.SCHEMA_PATH_PREFIX
        if not path_prefix.startswith("^"):
            path_prefix = (
                "^" + path_prefix
            )  # make sure regex only matches from the start

        for path, path_regex, method, view in endpoints:
            # emit queued up warnings/error that happened prior to generation (decoration)
            for w in get_override(view, "warnings", []):
                warn(w)
            for e in get_override(view, "errors", []):
                error(e)

            view.request = spectacular_settings.GET_MOCK_REQUEST(
                method, path, view, input_request
            )

            if not (public or self.has_view_permissions(path, method, view)):
                continue

            # Remove versioning api

            assert isinstance(view.schema, AutoSchema), (
                f"Incompatible AutoSchema used on View {view.__class__}. Is DRF's "
                f'DEFAULT_SCHEMA_CLASS pointing to "drf_spectacular.openapi.AutoSchema" '
                f"or any other drf-spectacular compatible AutoSchema?"
            )
            with add_trace_message(getattr(view, "__class__", view)):
                operation = view.schema.get_operation(
                    path, path_regex, path_prefix, method, self.registry
                )

            # operation was manually removed via @extend_schema
            if not operation:
                continue

            if spectacular_settings.SCHEMA_PATH_PREFIX_TRIM:
                path = re.sub(
                    pattern=path_prefix, repl="", string=path, flags=re.IGNORECASE
                )

            if spectacular_settings.SCHEMA_PATH_PREFIX_INSERT:
                path = spectacular_settings.SCHEMA_PATH_PREFIX_INSERT + path

            if not path.startswith("/"):
                path = "/" + path

            if spectacular_settings.CAMELIZE_NAMES:
                path, operation = camelize_operation(path, operation)

            result.setdefault(path, {})
            result[path][method.lower()] = operation

        return result
