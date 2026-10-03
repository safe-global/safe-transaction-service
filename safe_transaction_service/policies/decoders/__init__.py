# SPDX-License-Identifier: FSL-1.1-MIT
"""
Registry of policy `data` decoders. Adding support for a policy is a new module here plus
one `register` call, see `base` for the design.
"""

from .base import (
    AbiPolicyDataDecoder,
    PolicyDataDecoder,
    PolicyDataDecoderRegistry,
)
from .cosigner import CoSignerPolicyDataDecoder
from .erc20_transfer import Erc20TransferPolicyDataDecoder

__all__ = [
    "AbiPolicyDataDecoder",
    "CoSignerPolicyDataDecoder",
    "Erc20TransferPolicyDataDecoder",
    "PolicyDataDecoder",
    "PolicyDataDecoderRegistry",
    "policy_data_decoder_registry",
]

# TODO: Add decoders for all policies
policy_data_decoder_registry = PolicyDataDecoderRegistry()
policy_data_decoder_registry.register(Erc20TransferPolicyDataDecoder())
policy_data_decoder_registry.register(CoSignerPolicyDataDecoder())
