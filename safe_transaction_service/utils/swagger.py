import re

from drf_yasg.inspectors import SwaggerAutoSchema


class CustomSwaggerSchema(SwaggerAutoSchema):
    VERSION_REGULAR_EXPRESSION = re.compile(r"v[\d]+")
    CUSTOM_TAGS = {
        "messages": ["messages"],
        "owners": ["owners"],
        "transaction": ["transactions"],
        "transfer": ["transactions"],
        "multisig-transaction": ["transactions"],
        "user-operation": ["4337"],
        "safe-operation": ["4337"],
    }

    def get_tags(self, operation_keys=None):
        """
        The method `get_tags` defined by default just gets the `operation_keys` (generated from the
        url) and return the first element, for example in our case being all the tags `v1`, `v2`, etc.

        We are now defining some logic to generate `tags`:
        - If they are explicitly defined in the view, we keep that (`self.overrides`).
        - If the `operation_id` contains any of the words defined, we override the tag.
        - Otherwise, just iterate the `operation_keys` and return

        :param operation_keys:
        :return:
        """
        operation_keys = operation_keys or self.operation_keys

        if tags := self.overrides.get("tags"):
            return tags

        if len(operation_keys) == 1:
            return list(operation_keys)

        operation_id = self.get_operation_id()
        for key, tags in self.CUSTOM_TAGS.items():
            if key in operation_id:
                return tags[:]

        for operation_key in operation_keys:
            if not self.VERSION_REGULAR_EXPRESSION.match(operation_key):
                return [operation_key]
        return []  # This should never happen
