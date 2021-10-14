open_zeppelin_admin_upgradeability_proxy = [
    {
        "inputs": [
            {"internalType": "address", "name": "_logic", "type": "address"},
            {"internalType": "address", "name": "_admin", "type": "address"},
            {"internalType": "bytes", "name": "_data", "type": "bytes"},
        ],
        "payable": True,
        "stateMutability": "payable",
        "type": "constructor",
    },
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

open_zeppelin_proxy_admin = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "previousOwner",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "newOwner",
                "type": "address",
            },
        ],
        "name": "OwnershipTransferred",
        "type": "event",
    },
    {
        "constant": False,
        "inputs": [
            {
                "internalType": "contract AdminUpgradeabilityProxy",
                "name": "proxy",
                "type": "address",
            },
            {"internalType": "address", "name": "newAdmin", "type": "address"},
        ],
        "name": "changeProxyAdmin",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {
                "internalType": "contract AdminUpgradeabilityProxy",
                "name": "proxy",
                "type": "address",
            }
        ],
        "name": "getProxyAdmin",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {
                "internalType": "contract AdminUpgradeabilityProxy",
                "name": "proxy",
                "type": "address",
            }
        ],
        "name": "getProxyImplementation",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "isOwner",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [],
        "name": "renounceOwnership",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"internalType": "address", "name": "newOwner", "type": "address"}],
        "name": "transferOwnership",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "internalType": "contract AdminUpgradeabilityProxy",
                "name": "proxy",
                "type": "address",
            },
            {"internalType": "address", "name": "implementation", "type": "address"},
        ],
        "name": "upgrade",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "internalType": "contract AdminUpgradeabilityProxy",
                "name": "proxy",
                "type": "address",
            },
            {"internalType": "address", "name": "implementation", "type": "address"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
        ],
        "name": "upgradeAndCall",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
]
