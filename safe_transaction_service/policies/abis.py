# SPDX-License-Identifier: FSL-1.1-MIT
"""
`SafePolicyGuard` ABI, reduced to what the service needs: the indexed events and the
configuration entrypoints, so `TxDecoder` can decode guard calldata.

https://github.com/safe-research/policy-engine
"""

# struct Configuration { address target; bytes4 selector; Operation operation; address policy; bytes data; }
_CONFIGURATION_COMPONENTS = [
    {"internalType": "address", "name": "target", "type": "address"},
    {"internalType": "bytes4", "name": "selector", "type": "bytes4"},
    {"internalType": "enum Operation", "name": "operation", "type": "uint8"},
    {"internalType": "address", "name": "policy", "type": "address"},
    {"internalType": "bytes", "name": "data", "type": "bytes"},
]

_CONFIGURATIONS_INPUT = {
    "components": _CONFIGURATION_COMPONENTS,
    "internalType": "struct SafePolicyGuard.Configuration[]",
    "name": "configurations",
    "type": "tuple[]",
}

SAFE_POLICY_GUARD_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "safe",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "target",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "bytes4",
                "name": "selector",
                "type": "bytes4",
            },
            {
                "indexed": False,
                "internalType": "enum Operation",
                "name": "operation",
                "type": "uint8",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "policy",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "bytes",
                "name": "data",
                "type": "bytes",
            },
        ],
        "name": "PolicyConfirmed",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "safe",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "root",
                "type": "bytes32",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "timestamp",
                "type": "uint256",
            },
        ],
        "name": "RootConfigured",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "safe",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "root",
                "type": "bytes32",
            },
        ],
        "name": "RootInvalidated",
        "type": "event",
    },
    {
        "inputs": [_CONFIGURATIONS_INPUT],
        "name": "configureImmediately",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [_CONFIGURATIONS_INPUT],
        "name": "applyConfiguration",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "configureRoot", "type": "bytes32"}
        ],
        "name": "requestConfiguration",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "configureRoot", "type": "bytes32"}
        ],
        "name": "invalidateRoot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
