from hexbytes import HexBytes

type_0_tx = {
    "tx": {
        "blockHash": HexBytes(
            "0x153276c610e9d2e0ca737377c6c877d6cb4913b80324a2ebb13cb8ff7e899f17"
        ),
        "blockNumber": 10137240,
        "from": "0x7ed8e2004a9ff9Ea76119EF7CCA2D721a0a95254",
        "gas": 83361,
        "gasPrice": 20000000000,
        "hash": HexBytes(
            "0x58863b13ccfc6904c0e7f277b099cd9282aa624d1d1ea3ee05644aa9e4283962"
        ),
        "input": "0xf6838a720000000000000000000000000000000000000000000000000000000000000002",
        "nonce": 1,
        "to": "0xbCF935D206Ca32929e1b887a07Ed240f0D8CCD22",
        "transactionIndex": 113,
        "value": 50000000000000000,
        "type": 0,
        "chainId": 1,
        "v": 37,
        "r": HexBytes(
            "0x7da7ec6f26c61354c37d4d30429e28ecd35b9a6362f1d79bee109c387eb07518"
        ),
        "s": HexBytes(
            "0x6bdf364ca0a9cdf5ae199f69e282d3ca99a54b2b9ee19419dfae2577d2ad221b"
        ),
    },
    "receipt": {
        "blockHash": HexBytes(
            "0x153276c610e9d2e0ca737377c6c877d6cb4913b80324a2ebb13cb8ff7e899f17"
        ),
        "blockNumber": 10137240,
        "contractAddress": None,
        "cumulativeGasUsed": 9659305,
        "effectiveGasPrice": 20000000000,
        "from": "0x7ed8e2004a9ff9Ea76119EF7CCA2D721a0a95254",
        "gasUsed": 64124,
        "logs": [
            {
                "address": "0xbCF935D206Ca32929e1b887a07Ed240f0D8CCD22",
                "topics": [
                    HexBytes(
                        "0xce7dc747411ac40191c5335943fcc79d8c2d8c01ca5ae83d9fed160409fa6120"
                    ),
                    HexBytes(
                        "0x000000000000000000000000082cd8f1bf25329528fddcb7b365abb34911ac6b"
                    ),
                    HexBytes(
                        "0x0000000000000000000000007ed8e2004a9ff9ea76119ef7cca2d721a0a95254"
                    ),
                ],
                "data": HexBytes(
                    "0x0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000005ecc3350"
                ),
                "blockNumber": 10137240,
                "transactionHash": HexBytes(
                    "0x58863b13ccfc6904c0e7f277b099cd9282aa624d1d1ea3ee05644aa9e4283962"
                ),
                "transactionIndex": 113,
                "blockHash": HexBytes(
                    "0x153276c610e9d2e0ca737377c6c877d6cb4913b80324a2ebb13cb8ff7e899f17"
                ),
                "logIndex": 134,
                "removed": False,
            },
            {
                "address": "0xbCF935D206Ca32929e1b887a07Ed240f0D8CCD22",
                "topics": [
                    HexBytes(
                        "0x9ea70f0eb33d898c3336ecf2c0e3cf1c0195c13ad3fbcb34447777dbfd5ff2d0"
                    ),
                    HexBytes(
                        "0x0000000000000000000000007ed8e2004a9ff9ea76119ef7cca2d721a0a95254"
                    ),
                ],
                "data": HexBytes(
                    "0x0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000005ecc3350"
                ),
                "blockNumber": 10137240,
                "transactionHash": HexBytes(
                    "0x58863b13ccfc6904c0e7f277b099cd9282aa624d1d1ea3ee05644aa9e4283962"
                ),
                "transactionIndex": 113,
                "blockHash": HexBytes(
                    "0x153276c610e9d2e0ca737377c6c877d6cb4913b80324a2ebb13cb8ff7e899f17"
                ),
                "logIndex": 135,
                "removed": False,
            },
        ],
        "logsBloom": HexBytes(
            "0x00000000000000010000000000000000000000000400000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000002000100001000000000000100000000000000000000000000008000000000000000000000000040000000000000000000000000000000000000080000000000000000000000000000000000000000000000000000100000040000000000000000000100000000000000000000000000000000000000000000000000000000000000000000040"
        ),
        "status": 1,
        "to": "0xbCF935D206Ca32929e1b887a07Ed240f0D8CCD22",
        "transactionHash": HexBytes(
            "0x58863b13ccfc6904c0e7f277b099cd9282aa624d1d1ea3ee05644aa9e4283962"
        ),
        "transactionIndex": 113,
        "type": 0,
    },
}

type_2_tx = {
    "tx": {
        "blockHash": HexBytes(
            "0x8d54f5d3837503abd9058de0fb3197077289855e1a009794598e968f1c5a4d0e"
        ),
        "blockNumber": 17137240,
        "from": "0x1c7c15e45ad58d8b487B028fe0842c702595E0D8",
        "gas": 94813,
        "gasPrice": 32297846431,
        "maxPriorityFeePerGas": 71866838,
        "maxFeePerGas": 40579350040,
        "hash": HexBytes(
            "0xf6025f11f8583d30d3a227bc4616cb377c29e797e5f18ff881397988ac8a644a"
        ),
        "input": "0xa9059cbb000000000000000000000000c8f0f077e53f86f6c11a59c519f953338fba7f0000000000000000000000000000000000000000000000000000000005f4173c80",
        "nonce": 1,
        "to": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "transactionIndex": 108,
        "value": 0,
        "type": 2,
        "accessList": [],
        "chainId": 1,
        "v": 0,
        "r": HexBytes(
            "0x0dbc6fb91dca40e9105bdd7b51853a18bdae73f12b28444dc5d3d2feed7914ff"
        ),
        "s": HexBytes(
            "0x57f7c1e2da8f0595b0874298eee775b35754ea8c97b43845e134a4a08d5d0ded"
        ),
    },
    "receipt": {
        "blockHash": HexBytes(
            "0x8d54f5d3837503abd9058de0fb3197077289855e1a009794598e968f1c5a4d0e"
        ),
        "blockNumber": 17137240,
        "contractAddress": None,
        "cumulativeGasUsed": 9777448,
        "effectiveGasPrice": 32297846431,
        "from": "0x1c7c15e45ad58d8b487B028fe0842c702595E0D8",
        "gasUsed": 63209,
        "logs": [
            {
                "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "topics": [
                    HexBytes(
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
                    ),
                    HexBytes(
                        "0x0000000000000000000000001c7c15e45ad58d8b487b028fe0842c702595e0d8"
                    ),
                    HexBytes(
                        "0x000000000000000000000000c8f0f077e53f86f6c11a59c519f953338fba7f00"
                    ),
                ],
                "data": HexBytes(
                    "0x00000000000000000000000000000000000000000000000000000005f4173c80"
                ),
                "blockNumber": 17137240,
                "transactionHash": HexBytes(
                    "0xf6025f11f8583d30d3a227bc4616cb377c29e797e5f18ff881397988ac8a644a"
                ),
                "transactionIndex": 108,
                "blockHash": HexBytes(
                    "0x8d54f5d3837503abd9058de0fb3197077289855e1a009794598e968f1c5a4d0e"
                ),
                "logIndex": 218,
                "removed": False,
            }
        ],
        "logsBloom": HexBytes(
            "0x00000008000000000000000000000000000000000020000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000008000000000000000000000000000000004000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000100000000000000000010000000080000000000000000000000000000010000000000000000002000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000400000000000000000000"
        ),
        "status": 1,
        "to": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "transactionHash": HexBytes(
            "0xf6025f11f8583d30d3a227bc4616cb377c29e797e5f18ff881397988ac8a644a"
        ),
        "transactionIndex": 108,
        "type": 2,
    },
}
