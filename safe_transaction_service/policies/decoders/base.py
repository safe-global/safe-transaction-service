# SPDX-License-Identifier: FSL-1.1-MIT
"""
Decoding of the `data` a Safe configured a policy with.

`PolicyConfirmed` carries `policy` (an address) and `data`. The layout of
`data` is defined by that policy's `configure(safe, access, data)`, so decoding needs two
lookups, kept apart because one is data and the other is code:

1. address to policy name: `PolicyContract`, seeded per chain and admin editable.
2. policy name to layout: one `PolicyDataDecoder` per policy.

`PolicyDataDecoderRegistry` chains them, and is the only thing serializers need to know
about. Nothing decoded is persisted, so adding or fixing a decoder needs no backfill.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from eth_abi import decode as decode_abi
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.utils import fast_to_checksum_address
from safe_eth.util.util import to_0x_hex_str

from ..models import PolicyContract

logger = logging.getLogger(__name__)


def split_abi_tuple(abi_type: str) -> list[str]:
    """
    :param abi_type: A tuple type, e.g. `(address,bool)`
    :return: The member types, e.g. `["address", "bool"]`
    """
    members = []
    depth = 0
    member_start = 1  # Skip the opening parenthesis
    for position, character in enumerate(abi_type):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
            if not depth:  # Closing parenthesis of `abi_type` itself
                members.append(abi_type[member_start:position])
        elif character == "," and depth == 1:
            members.append(abi_type[member_start:position])
            member_start = position + 1
    return members


class PolicyDataDecoder(ABC):
    """Decodes the `data` blob of one policy."""

    name: str

    @abstractmethod
    def decode(self, data: bytes) -> dict[str, Any]:
        """
        :param data: `data` as emitted by `PolicyConfirmed`
        :return: JSON serializable parameters
        :raises DecodingError: `data` does not match this policy
        :raises ValueError: `data` does not match this policy
        """


class AbiPolicyDataDecoder(PolicyDataDecoder):
    """
    `PolicyDataDecoder` for a policy whose `data` is a plain abi encoded tuple, which is
    every policy so far. A subclass only declares types and names, formatting lives here.
    """

    # `eth_abi` types, matching the `abi.decode` call in the policy's `configure`
    abi_types: tuple[str, ...]
    # Output keys, one per element of `abi_types`
    field_names: tuple[str, ...]
    # Member names for the struct in `abi_types`, if there is one
    struct_names: tuple[str, ...] = ()

    def decode(self, data: bytes) -> dict[str, Any]:
        values = decode_abi(self.abi_types, data)
        return {
            name: self._to_json(abi_type, value)
            for name, abi_type, value in zip(
                self.field_names, self.abi_types, values, strict=True
            )
        }

    def _to_json(self, abi_type: str, value: Any) -> Any:
        """
        Convert one decoded value to a JSON serializable type, driven by its abi type:
        arrays become lists, structs become dictionaries keyed by `struct_names`,
        addresses are checksummed and `bytes` become hexadecimal.
        """
        if abi_type.endswith("]"):  # Array, fixed or dynamic size
            element_type = abi_type[: abi_type.rindex("[")]
            return [self._to_json(element_type, element) for element in value]
        if abi_type.startswith("("):  # Struct
            return {
                name: self._to_json(member_type, member)
                for name, member_type, member in zip(
                    self.struct_names, split_abi_tuple(abi_type), value, strict=True
                )
            }
        if abi_type == "address":
            return fast_to_checksum_address(value)
        if abi_type.startswith("bytes"):
            return to_0x_hex_str(value)
        return value


class PolicyDataDecoderRegistry:
    """Maps a policy address to its decoder, through `PolicyContract.name`."""

    def __init__(self):
        self._decoders: dict[str, PolicyDataDecoder] = {}

    def register(self, decoder: PolicyDataDecoder) -> None:
        """
        Index `decoder` under its name. Registering a name twice is a programming error, as
        one of the two decoders would silently never be used
        """
        if decoder.name in self._decoders:
            raise ValueError(f"A decoder for {decoder.name} is already registered")
        self._decoders[decoder.name] = decoder

    def decode(
        self, policy: ChecksumAddress, data: bytes | memoryview | None
    ) -> dict[str, Any] | None:
        """
        :return: `{"policy_name": ..., "parameters": {...}}`, or `None` if the policy is not
            known or `data` does not decode
        """
        name = PolicyContract.objects.get_name_for_address(policy)
        decoder = self._decoders.get(name) if name else None
        if decoder is None:
            return None

        data = HexBytes(data or b"")
        try:
            return {"policy_name": name, "parameters": decoder.decode(data)}
        except (DecodingError, ValueError, TypeError):
            logger.warning(
                "Cannot decode data=%s for policy=%s name=%s",
                to_0x_hex_str(data),
                policy,
                name,
            )
            return None
