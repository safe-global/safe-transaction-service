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
from collections.abc import Sequence
from functools import cached_property
from typing import Any

from eth_abi import decode as decode_abi
from eth_abi.exceptions import DecodingError
from eth_typing import ABIComponent, ABIFunction, ChecksumAddress
from hexbytes import HexBytes
from safe_eth.util.util import to_0x_hex_str
from web3._utils.abi import get_abi_input_types, map_abi_data, named_tree
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS, abi_bytes_to_hex

from ..models import PolicyContract

logger = logging.getLogger(__name__)

# Checksum addresses and turn `bytes` into hexadecimal, so the result is JSON serializable.
# Same normalizers `TxDecoder` uses for transaction data
RETURN_NORMALIZERS = BASE_RETURN_NORMALIZERS + [abi_bytes_to_hex]


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
    `PolicyDataDecoder` for a policy whose `data` is an abi encoded tuple, which is every
    policy so far. A subclass only declares the abi inputs of the `abi.decode` call in the
    policy's `configure`, copied from the contract abi.
    """

    abi_inputs: Sequence[ABIComponent]

    @cached_property
    def abi_types(self) -> list[str]:
        # `abi_inputs` as a function fragment, the shape the web3.py helpers expect
        return get_abi_input_types(
            ABIFunction(
                type="function",
                name="configure",
                inputs=list(self.abi_inputs),
                outputs=[],
            )
        )

    def decode(self, data: bytes) -> dict[str, Any]:
        decoded = decode_abi(self.abi_types, data)
        normalized = map_abi_data(RETURN_NORMALIZERS, self.abi_types, decoded)
        return named_tree(self.abi_inputs, normalized)


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
