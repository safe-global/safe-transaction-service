# SPDX-License-Identifier: FSL-1.1-MIT
from safe_eth.eth.utils import fast_is_checksum_address

from safe_transaction_service.history.exceptions import BannedSafeException
from safe_transaction_service.history.models import SafeContract


class BannedSafeMixin:
    """
    Rejects any request for a banned Safe (``SafeContract.banned``) with
    HTTP 451 Unavailable For Legal Reasons. The Safe is resolved from the
    ``address`` URL kwarg and checked with a single indexed database lookup
    (not the cached banned set, so a ban is enforced on the API immediately),
    no RPC calls are involved.
    """

    def initial(self, request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        address = kwargs.get("address")
        if (
            address
            and fast_is_checksum_address(address)
            and SafeContract.objects.banned(addresses=[address]).exists()
        ):
            raise BannedSafeException()
