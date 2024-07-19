from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse

from django import forms
from django.core import exceptions
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from hexbytes import HexBytes
from web3.types import LogReceipt


class HexField(forms.CharField):
    # TODO Move this to safe-eth-py
    default_error_messages = {
        "invalid": _("Enter a valid hexadecimal."),
    }

    def to_python(self, value: Union[str, bytes, memoryview]) -> HexBytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, memoryview):
            return HexBytes(bytes(value))
        if value in self.empty_values:
            return None

        value = str(value)
        if self.strip:
            try:
                value = HexBytes(value.strip())
            except (TypeError, ValueError) as exc:
                raise exceptions.ValidationError(
                    self.error_messages["invalid"],
                    code="invalid",
                ) from exc
        return value

    def prepare_value(self, value: memoryview) -> str:
        return "0x" + bytes(value).hex() if value else ""


def clean_receipt_log(receipt_log: LogReceipt) -> Optional[Dict[str, Any]]:
    """
    Clean receipt log and make them JSON compliant

    :param receipt_log:
    :return:
    """

    parsed_log = {
        "address": receipt_log["address"],
        "data": receipt_log["data"].hex(),
        "topics": [topic.hex() for topic in receipt_log["topics"]],
    }
    return parsed_log


def validate_url(url: str) -> None:
    result = urlparse(url)
    if not all(
        (
            result.scheme
            in (
                "http",
                "https",
            ),
            result.netloc,
        )
    ):
        raise ValidationError(f"{url} is not a valid url")
