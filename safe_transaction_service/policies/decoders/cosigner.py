# SPDX-License-Identifier: FSL-1.1-MIT
from ..constants import COSIGNER_POLICY
from .base import AbiPolicyDataDecoder


class CoSignerPolicyDataDecoder(AbiPolicyDataDecoder):
    """``abi.decode(data, (address))``, the co-signer required for the access selector."""

    name = COSIGNER_POLICY
    abi_types = ("address",)
    field_names = ("cosigner",)
