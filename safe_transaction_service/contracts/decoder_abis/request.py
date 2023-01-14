request_erc20_proxy = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": False,
                "internalType": "address",
                "name": "tokenAddress",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "to",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "bytes",
                "name": "paymentReference",
                "type": "bytes",
            },
        ],
        "name": "TransferWithReference",
        "type": "event",
    },
    {"payable": True, "stateMutability": "payable", "type": "fallback"},
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "_tokenAddress", "type": "address"},
            {"internalType": "address", "name": "_to", "type": "address"},
            {"internalType": "uint256", "name": "_amount", "type": "uint256"},
            {"internalType": "bytes", "name": "_paymentReference", "type": "bytes"},
        ],
        "name": "transferFromWithReference",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
request_erc20_swap_to_pay = [
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "_swapRouterAddress",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "_paymentProxyAddress",
                "type": "address",
            },
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
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
            {"internalType": "address", "name": "_erc20Address", "type": "address"}
        ],
        "name": "approvePaymentProxyToSpend",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "_erc20Address", "type": "address"}
        ],
        "name": "approveRouterToSpend",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
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
        "constant": True,
        "inputs": [],
        "name": "paymentProxy",
        "outputs": [
            {"internalType": "contract IERC20FeeProxy", "name": "", "type": "address"}
        ],
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
        "inputs": [
            {
                "internalType": "address",
                "name": "_paymentProxyAddress",
                "type": "address",
            }
        ],
        "name": "setPaymentProxy",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "internalType": "address",
                "name": "_newSwapRouterAddress",
                "type": "address",
            }
        ],
        "name": "setRouter",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "swapRouter",
        "outputs": [
            {
                "internalType": "contract IUniswapV2Router02",
                "name": "",
                "type": "address",
            }
        ],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "address", "name": "_to", "type": "address"},
            {"internalType": "uint256", "name": "_amount", "type": "uint256"},
            {"internalType": "uint256", "name": "_amountInMax", "type": "uint256"},
            {"internalType": "address[]", "name": "_path", "type": "address[]"},
            {"internalType": "bytes", "name": "_paymentReference", "type": "bytes"},
            {"internalType": "uint256", "name": "_feeAmount", "type": "uint256"},
            {"internalType": "address", "name": "_feeAddress", "type": "address"},
            {"internalType": "uint256", "name": "_deadline", "type": "uint256"},
        ],
        "name": "swapTransferWithReference",
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
]
request_ethereum_proxy = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": False,
                "internalType": "address",
                "name": "to",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "bytes",
                "name": "paymentReference",
                "type": "bytes",
            },
        ],
        "name": "TransferWithReference",
        "type": "event",
    },
    {"payable": True, "stateMutability": "payable", "type": "fallback"},
    {
        "constant": False,
        "inputs": [
            {"internalType": "address payable", "name": "_to", "type": "address"},
            {"internalType": "bytes", "name": "_paymentReference", "type": "bytes"},
        ],
        "name": "transferWithReference",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
]
