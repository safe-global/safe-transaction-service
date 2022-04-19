from hexbytes import HexBytes

type_0_tx = {
    "tx": {
        "blockHash": HexBytes(
            "0x062b97322d353ee94bea68bf2b131420f399e8dcca74e235fe4ef730f7111691"
        ),
        "blockNumber": 9030821,
        "chainId": "0x4",
        "condition": None,
        "creates": None,
        "from": "0x8305aBB71A2354C98433a82F108Df73820CE3133",
        "gas": 3000000,
        "gasPrice": 1000000000,
        "hash": HexBytes(
            "0xc2f804ef639b534b7cd30bf3062d71baa324233cfdf2f42e62a090aea1606ae2"
        ),
        "input": "0xa9059cbb0000000000000000000000009bc7d0c2850184c5f75f5e3a9e9dec7491f0103a00000000000000000000000000000000000000000000152d02c7e14af6800000",
        "nonce": 1776,
        "publicKey": HexBytes(
            "0xb7fe8abd703add5b75ca3c726980f2fadeb19d3fed6156f4815e00c7bbbe4481d52eeda616f93bcf460406580cb8b5ab0d32a2675b5c4a98f28cc9e1dc921d84"
        ),
        "r": HexBytes(
            "0x9e52b424ed922806e0f73fe835bf22df8caa7c3bcbe23dd6a329899a6c938ca2"
        ),
        "raw": HexBytes(
            "0xf8ab8206f0843b9aca00832dc6c094c666d239cbda32aa7ebca894b6dc598ddb88128580b844a9059cbb0000000000000000000000009bc7d0c2850184c5f75f5e3a9e9dec7491f0103a00000000000000000000000000000000000000000000152d02c7e14af68000002ca09e52b424ed922806e0f73fe835bf22df8caa7c3bcbe23dd6a329899a6c938ca2a0785f6cfd004e1cb617004d9f1357e76f55ff4ecfa24476712784be1d9e297b09"
        ),
        "s": HexBytes(
            "0x785f6cfd004e1cb617004d9f1357e76f55ff4ecfa24476712784be1d9e297b09"
        ),
        "standardV": 1,
        "to": "0xC666d239cbda32AA7ebCA894B6dC598dDb881285",
        "transactionIndex": 30,
        "type": "0x0",
        "v": 44,
        "value": 0,
    },
    "receipt": {
        "blockHash": HexBytes(
            "0x062b97322d353ee94bea68bf2b131420f399e8dcca74e235fe4ef730f7111691"
        ),
        "blockNumber": 9030821,
        "contractAddress": None,
        "cumulativeGasUsed": 10058813,
        "effectiveGasPrice": 1000000000,
        "from": "0x8305aBB71A2354C98433a82F108Df73820CE3133",
        "gasUsed": 34573,
        "logs": [
            {
                "address": "0xC666d239cbda32AA7ebCA894B6dC598dDb881285",
                "blockHash": HexBytes(
                    "0x062b97322d353ee94bea68bf2b131420f399e8dcca74e235fe4ef730f7111691"
                ),
                "blockNumber": 9030821,
                "data": "0x00000000000000000000000000000000000000000000152d02c7e14af6800000",
                "logIndex": 85,
                "removed": False,
                "topics": [
                    HexBytes(
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
                    ),
                    HexBytes(
                        "0x0000000000000000000000008305abb71a2354c98433a82f108df73820ce3133"
                    ),
                    HexBytes(
                        "0x0000000000000000000000009bc7d0c2850184c5f75f5e3a9e9dec7491f0103a"
                    ),
                ],
                "transactionHash": HexBytes(
                    "0xc2f804ef639b534b7cd30bf3062d71baa324233cfdf2f42e62a090aea1606ae2"
                ),
                "transactionIndex": 30,
                "transactionLogIndex": "0x0",
                "type": "mined",
            }
        ],
        "logsBloom": HexBytes(
            "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002000000000000010000000000000000000000008010000000000000000000000000000000000000000000000000000000000000000000000400000000000000000000010000000000000000000000000000000000000000008000000008000000000000000000000000000000000000000000000000000000000000000000000040000000000000000000002000000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000004000000000000"
        ),
        "status": 1,
        "to": "0xC666d239cbda32AA7ebCA894B6dC598dDb881285",
        "transactionHash": HexBytes(
            "0xc2f804ef639b534b7cd30bf3062d71baa324233cfdf2f42e62a090aea1606ae2"
        ),
        "transactionIndex": 30,
        "type": "0x0",
    },
}

type_2_tx = {
    "tx": {
        "accessList": [],
        "blockHash": HexBytes(
            "0x0113567d08f0fd2f5aef6593aa9055d6fb67af0f2bd63667c6fa06cbbf440b1a"
        ),
        "blockNumber": 10530755,
        "chainId": "0x4",
        "condition": None,
        "creates": None,
        "from": "0xa7a82DD06901F29aB14AF63faF3358AD101724A8",
        "gas": 60000,
        "gasPrice": 2500000022,
        "hash": HexBytes(
            "0x02d70902fed45c6e3dc602d6df9ef19596f3ff7255a6bd261a62b474c95ef232"
        ),
        "input": "0x",
        "maxFeePerGas": 2500000042,
        "maxPriorityFeePerGas": 2500000000,
        "nonce": 4523150,
        "publicKey": HexBytes(
            "0x873c2c1b9852ac9b0de12bafa88cadee81bb9ee549248ba3b250ce0153e277a6233242d2fdc02"
            "eff09c5399f71f25a4c4476517b95124cd0aaad67d3be11fe91"
        ),
        "r": HexBytes(
            "0x0c03fe496f4bf8cfc4ced71044955213d0f3d076460ea45803f219fc89deb424"
        ),
        "raw": HexBytes(
            "0x02f875048345048e849502f900849502f92a82ea6094a417ef0c2ec3d820fbb3d9b6bebc39d35"
            "361584988016345785d8a000080c080a00c03fe496f4bf8cfc4ced71044955213d0f3d076460ea4"
            "5803f219fc89deb424a055604f66eb0800546dcdd38933de856acc2f6ff423ab39bedaa7f2cb968"
            "ea252"
        ),
        "s": HexBytes(
            "0x55604f66eb0800546dcdd38933de856acc2f6ff423ab39bedaa7f2cb968ea252"
        ),
        "to": "0xa417eF0c2ec3D820fbb3d9B6BeBc39d353615849",
        "transactionIndex": 15,
        "type": "0x2",
        "v": 0,
        "value": 100000000000000000,
    },
    "receipt": {
        "blockHash": HexBytes(
            "0x0113567d08f0fd2f5aef6593aa9055d6fb67af0f2bd63667c6fa06cbbf440b1a"
        ),
        "blockNumber": 10530755,
        "contractAddress": None,
        "cumulativeGasUsed": 977116,
        "effectiveGasPrice": 2500000022,
        "from": "0xa7a82DD06901F29aB14AF63faF3358AD101724A8",
        "gasUsed": 21000,
        "logs": [],
        "logsBloom": HexBytes(
            "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        ),
        "status": 1,
        "to": "0xa417eF0c2ec3D820fbb3d9B6BeBc39d353615849",
        "transactionHash": HexBytes(
            "0x02d70902fed45c6e3dc602d6df9ef19596f3ff7255a6bd261a62b474c95ef232"
        ),
        "transactionIndex": 15,
        "type": "0x2",
    },
}
