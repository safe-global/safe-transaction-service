balancer_bactions = [
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BFactory", "name": "factory", "type": "address"},
            {"internalType": "address[]", "name": "tokens", "type": "address[]"},
            {"internalType": "uint256[]", "name": "balances", "type": "uint256[]"},
            {"internalType": "uint256[]", "name": "denorms", "type": "uint256[]"},
            {"internalType": "uint256", "name": "swapFee", "type": "uint256"},
            {"internalType": "bool", "name": "finalize", "type": "bool"},
        ],
        "name": "create",
        "outputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"}
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"}
        ],
        "name": "finalize",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "uint256", "name": "poolAmountOut", "type": "uint256"},
            {"internalType": "uint256[]", "name": "maxAmountsIn", "type": "uint256[]"},
        ],
        "name": "joinPool",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "uint256", "name": "tokenAmountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "minPoolAmountOut", "type": "uint256"},
        ],
        "name": "joinswapExternAmountIn",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "address", "name": "newController", "type": "address"},
        ],
        "name": "setController",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "bool", "name": "publicSwap", "type": "bool"},
        ],
        "name": "setPublicSwap",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "uint256", "name": "newFee", "type": "uint256"},
        ],
        "name": "setSwapFee",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"internalType": "contract BPool", "name": "pool", "type": "address"},
            {"internalType": "address[]", "name": "tokens", "type": "address[]"},
            {"internalType": "uint256[]", "name": "balances", "type": "uint256[]"},
            {"internalType": "uint256[]", "name": "denorms", "type": "uint256[]"},
        ],
        "name": "setTokens",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

balancer_exchange_proxy = [
    {
        "inputs": [{"internalType": "address", "name": "_weth", "type": "address"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {
        "anonymous": True,
        "inputs": [
            {
                "indexed": True,
                "internalType": "bytes4",
                "name": "sig",
                "type": "bytes4",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "caller",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "bytes",
                "name": "data",
                "type": "bytes",
            },
        ],
        "name": "LOG_CALL",
        "type": "event",
    },
    {"payable": True, "stateMutability": "payable", "type": "fallback"},
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint256", "name": "minTotalAmountOut", "type": "uint256"},
        ],
        "name": "batchEthInSwapExactIn",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountOut", "type": "uint256"}
        ],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenOut", "type": "address"},
        ],
        "name": "batchEthInSwapExactOut",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountIn", "type": "uint256"}
        ],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "uint256", "name": "totalAmountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "minTotalAmountOut", "type": "uint256"},
        ],
        "name": "batchEthOutSwapExactIn",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountOut", "type": "uint256"}
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "uint256", "name": "maxTotalAmountIn", "type": "uint256"},
        ],
        "name": "batchEthOutSwapExactOut",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountIn", "type": "uint256"}
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint256", "name": "totalAmountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "minTotalAmountOut", "type": "uint256"},
        ],
        "name": "batchSwapExactIn",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountOut", "type": "uint256"}
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "pool", "type": "address"},
                    {
                        "internalType": "uint256",
                        "name": "tokenInParam",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "tokenOutParam",
                        "type": "uint256",
                    },
                    {"internalType": "uint256", "name": "maxPrice", "type": "uint256"},
                ],
                "internalType": "struct ExchangeProxy.Swap[]",
                "name": "swaps",
                "type": "tuple[]",
            },
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint256", "name": "maxTotalAmountIn", "type": "uint256"},
        ],
        "name": "batchSwapExactOut",
        "outputs": [
            {"internalType": "uint256", "name": "totalAmountIn", "type": "uint256"}
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
