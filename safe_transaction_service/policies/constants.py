# SPDX-License-Identifier: FSL-1.1-MIT
"""
Policy Engine deployments per `chain_id`.

Source: https://github.com/safe-research/policy-engine/blob/main/networks.json

`setup_service` seeds `SafePolicyGuard` and `PolicyContract` from here, so a new
deployment only needs a new entry (or a row added through the admin).
"""

from dataclasses import dataclass

from eth_typing import ChecksumAddress, HexAddress, HexStr


def _checksum_address(address: str) -> ChecksumAddress:
    """Tag an already checksummed literal address as a `ChecksumAddress`."""
    return ChecksumAddress(HexAddress(HexStr(address)))


# Policy names, used to look up a `data` decoder. They match the contract names.
ALLOW_POLICY = "AllowPolicy"
ALLOWED_MODULE_POLICY = "AllowedModulePolicy"
COSIGNER_POLICY = "CoSignerPolicy"
DENY_POLICY = "DenyPolicy"
ERC20_APPROVE_POLICY = "ERC20ApprovePolicy"
ERC20_TRANSFER_POLICY = "ERC20TransferPolicy"
MULTISEND_POLICY = "MultiSendPolicy"
NATIVE_TRANSFER_POLICY = "NativeTransferPolicy"


@dataclass(frozen=True)
class GuardDeployment:
    """A `SafePolicyGuard` deployment whose events must be indexed."""

    address: ChecksumAddress
    # Block the guard was deployed on. Indexing starts here, so a wrong value
    # means either replaying the whole chain or missing events
    initial_block_number: int


GUARD_ADDRESS = _checksum_address("0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8")

GUARD_DEPLOYMENTS: dict[int, list[GuardDeployment]] = {
    31337: [GuardDeployment(GUARD_ADDRESS, 0)],
    11155111: [GuardDeployment(GUARD_ADDRESS, 11339539)],
}

POLICY_ADDRESSES: dict[ChecksumAddress, str] = {
    _checksum_address(address): name
    for address, name in {
        "0x3e40e32CE2BC4aFF4D1A9BE293C119ce4Fb52eAc": ALLOW_POLICY,
        "0x8d2fA07068F55a1934C6A4EdE1C460C3d7D50e4A": ALLOWED_MODULE_POLICY,
        "0xC49f4786aF99b7c3Edf0A3F71E6B969B76302ca5": COSIGNER_POLICY,
        "0xA78478404a909d9Fc4A693ed6c91508d0E6a071a": DENY_POLICY,
        "0x2382b4680C610788eD9b00046c0f7F979F195575": ERC20_APPROVE_POLICY,
        "0xec399EE72199DBc1f7DCf8b69cFa0290d1e06Fb7": ERC20_TRANSFER_POLICY,
        "0x297127E77B51bB9E3F4a59E6b8Ac4d42f99CdAD5": MULTISEND_POLICY,
        "0x77d29DEaE811D5E42fbe292d3f2729403e11cA3A": NATIVE_TRANSFER_POLICY,
    }.items()
}

POLICY_DEPLOYMENTS: dict[int, dict[ChecksumAddress, str]] = {
    31337: POLICY_ADDRESSES,
    11155111: POLICY_ADDRESSES,
}
