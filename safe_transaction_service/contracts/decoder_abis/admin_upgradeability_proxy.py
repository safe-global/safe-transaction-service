initializable_admin_upgradeability_proxy_abi = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": False,
                "internalType": "address",
                "name": "previousAdmin",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "newAdmin",
                "type": "address",
            },
        ],
        "name": "AdminChanged",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "implementation",
                "type": "address",
            }
        ],
        "name": "Upgraded",
        "type": "event",
    },
    {"payable": True, "stateMutability": "payable", "type": "fallback"},
    {
        "constant": False,
        "inputs": [],
        "name": "admin",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"internalType": "address", "name": "newAdmin", "type": "address"}],
        "name": "changeAdmin",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [],
        "name": "implementation",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "_logic", "type": "address"},
            {"internalType": "address", "name": "_admin", "type": "address"},
            {"internalType": "bytes", "name": "_data", "type": "bytes"},
        ],
        "name": "initialize",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "_logic", "type": "address"},
            {"internalType": "bytes", "name": "_data", "type": "bytes"},
        ],
        "name": "initialize",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "newImplementation", "type": "address"}
        ],
        "name": "upgradeTo",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "newImplementation", "type": "address"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
        ],
        "name": "upgradeToAndCall",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
]
