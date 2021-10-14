snapshot_delegate_registry_abi = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "delegator",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "id",
                "type": "bytes32",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "delegate",
                "type": "address",
            },
        ],
        "name": "ClearDelegate",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "delegator",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "id",
                "type": "bytes32",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "delegate",
                "type": "address",
            },
        ],
        "name": "SetDelegate",
        "type": "event",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "bytes32", "name": "", "type": "bytes32"},
        ],
        "name": "delegation",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "id", "type": "bytes32"},
            {"internalType": "address", "name": "delegate", "type": "address"},
        ],
        "name": "setDelegate",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "id", "type": "bytes32"}],
        "name": "clearDelegate",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
