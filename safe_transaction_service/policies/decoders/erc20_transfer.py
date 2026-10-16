# SPDX-License-Identifier: FSL-1.1-MIT
from ..constants import ERC20_TRANSFER_POLICY
from .base import AbiPolicyDataDecoder


class Erc20TransferPolicyDataDecoder(AbiPolicyDataDecoder):
    """
    ``struct RecipientData { address recipient; bool allowed; }``

    ``abi.decode(data, (RecipientData[]))``
    """

    name = ERC20_TRANSFER_POLICY
    abi_inputs = [
        {
            "name": "recipients",
            "type": "tuple[]",
            "components": [
                {"name": "recipient", "type": "address"},
                {"name": "allowed", "type": "bool"},
            ],
        }
    ]
