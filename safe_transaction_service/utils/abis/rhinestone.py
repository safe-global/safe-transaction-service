# SPDX-License-Identifier: FSL-1.1-MIT
# Rhinestone `SafeRelayExecutor`: permissionless wrapper used by the Rhinestone relay to sponsor
# Safe transactions. `execute` forwards `data` verbatim to `target` (Safe, MultiSendCallOnly or a
# canonical Safe ProxyFactory). Deployed with CREATE2 at the same address on every chain, e.g.
# https://optimistic.etherscan.io/address/0x781388759eacb9892f60d77d9a99c9be2f7f4ada
rhinestone_safe_relay_executor_abi = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "id",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "bytes32",
                "name": "contentHash",
                "type": "bytes32",
            },
        ],
        "name": "IntentExecuted",
        "type": "event",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "id", "type": "uint256"},
            {"internalType": "address", "name": "target", "type": "address"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
        ],
        "name": "execute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
