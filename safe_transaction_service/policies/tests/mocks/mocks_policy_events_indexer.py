# SPDX-License-Identifier: FSL-1.1-MIT
"""
`SafePolicyGuard` log receipts, captured from a local node running the contracts of
https://github.com/safe-research/policy-engine
"""

from hexbytes import HexBytes

SAFE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
OTHER_SAFE = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
GUARD = "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8"
TOKEN = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"
RECIPIENTS = (
    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
)
COSIGNER = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
ERC20_TRANSFER_POLICY = "0x37AB4Fd7eFaDfC6cc35e09196f74c19F163EdA43"
COSIGNER_POLICY = "0xC49f4786aF99b7c3Edf0A3F71E6B969B76302ca5"
ALLOW_POLICY = "0x3e40e32CE2BC4aFF4D1A9BE293C119ce4Fb52eAc"

policy_guard_log_receipts = [
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x0805fd3a44557acc0b6b56357d9772a45efa4ae754bdf9bbc469ffa2077cfd68"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0x0000000000000000000000009965507d1a55bcc2695c58ba16fb37d819b0a4dc"
            ),
        ],
        "data": HexBytes(
            "0xa9059cbb00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000037ab4fd7efadfc6cc35e09196f74c19f163eda43000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000020000000000000000000000003c44cdddb6a900fa2b585dd299e03d12fa4293bc000000000000000000000000000000000000000000000000000000000000000100000000000000000000000090f79bf6eb2c4f870365e785982e1f101e93b9060000000000000000000000000000000000000000000000000000000000000000"
        ),
        "blockNumber": 13,
        "transactionHash": HexBytes(
            "0x0d4bc33acdd42aa60631e8b746a43adac152d0901960cdec97c6b45c3805e268"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0xcce8ff0bc9d8344b9448a40b4cfb59cc4caca2547ea207cfaeb14df45033c3e2"
        ),
        "logIndex": 0,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x0805fd3a44557acc0b6b56357d9772a45efa4ae754bdf9bbc469ffa2077cfd68"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        ],
        "data": HexBytes(
            "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000c49f4786af99b7c3edf0a3f71e6b969b76302ca50000000000000000000000000000000000000000000000000000000000000080000000000000000000000000000000000000000000000000000000000000002000000000000000000000000015d34aaf54267db7d7c367839aaf71a00a2c6a65"
        ),
        "blockNumber": 13,
        "transactionHash": HexBytes(
            "0x0d4bc33acdd42aa60631e8b746a43adac152d0901960cdec97c6b45c3805e268"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0xcce8ff0bc9d8344b9448a40b4cfb59cc4caca2547ea207cfaeb14df45033c3e2"
        ),
        "logIndex": 1,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x0805fd3a44557acc0b6b56357d9772a45efa4ae754bdf9bbc469ffa2077cfd68"
            ),
            HexBytes(
                "0x00000000000000000000000070997970c51812dc3a010c7d01b50e0d17dc79c8"
            ),
            HexBytes(
                "0x0000000000000000000000009965507d1a55bcc2695c58ba16fb37d819b0a4dc"
            ),
        ],
        "data": HexBytes(
            "0x000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000003e40e32ce2bc4aff4d1a9be293c119ce4fb52eac00000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000"
        ),
        "blockNumber": 14,
        "transactionHash": HexBytes(
            "0xb218f0f6dda5faa139c8b2b704ebf377b12a6ba40bd851f6f961af3c7828526e"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0xcc9b41edd94e758e0cdb45b57fe0c8f8ecc90af1728c840791bb8b0c409ddbcb"
        ),
        "logIndex": 0,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x0805fd3a44557acc0b6b56357d9772a45efa4ae754bdf9bbc469ffa2077cfd68"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0x0000000000000000000000009965507d1a55bcc2695c58ba16fb37d819b0a4dc"
            ),
        ],
        "data": HexBytes(
            "0xa9059cbb000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000"
        ),
        "blockNumber": 15,
        "transactionHash": HexBytes(
            "0x4c7af9f885325e114886c6fb84d9ce5a0c0401d8cbc8d7c958b758d9b3809140"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0x5447fc9953a091ddb5e9127eb93e4f903c4e9d2aa6c2c7c1b5ad63c992d54bd8"
        ),
        "logIndex": 0,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x8857d111f216033018e32912740c76f34788b5b52d9a50933f748fce54af365b"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0xeabdc71f012a651cec38518c7166aaf6f216eb630c3d83cd605819cbc2983871"
            ),
        ],
        "data": HexBytes(
            "0x000000000000000000000000000000000000000000000000000000006a675dbe"
        ),
        "blockNumber": 16,
        "transactionHash": HexBytes(
            "0x3beae010635936730d2c356220689f8ce3276fe0c9b65a87df1e5b0bc033d407"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0xce246476d4aaeffed7d4015cada54a94a2e424f7632613ebe59090b0e1a32826"
        ),
        "logIndex": 0,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0xd9f6db884f5ac6cb83a417e89e1a1954779dc8201210c58868c63aaa16d6b2c6"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0xeabdc71f012a651cec38518c7166aaf6f216eb630c3d83cd605819cbc2983871"
            ),
        ],
        "data": "0x",
        "blockNumber": 17,
        "transactionHash": HexBytes(
            "0xeb7f123d3fb3c4008b9362715108bdafb9d0cfb7e55920436156120e50a3c7b6"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0x2d80c665bf15f256c82058f42607346407a67eb42771bc6b0aa3b364519c5654"
        ),
        "logIndex": 0,
        "removed": False,
    },
    {
        "address": "0xde4c448904537EBBA654Ac3803E7D74A77C7a1a8",
        "topics": [
            HexBytes(
                "0x8857d111f216033018e32912740c76f34788b5b52d9a50933f748fce54af365b"
            ),
            HexBytes(
                "0x000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
            ),
            HexBytes(
                "0xcf1c46fdbc3ff8d4abfc57c484da1125fcd79132525da06c93b39a5e979f7645"
            ),
        ],
        "data": HexBytes(
            "0x000000000000000000000000000000000000000000000000000000006a675dbe"
        ),
        "blockNumber": 18,
        "transactionHash": HexBytes(
            "0x09f9e1867b0a3a7c2a34979ec63b27a93ba2a0ec31e1c4228a6dcce94b1ad4c7"
        ),
        "transactionIndex": 0,
        "blockHash": HexBytes(
            "0x52dd5ee99583c04deafe81d84e7a0d613fb81995793ee33ce8d055da5a210cbb"
        ),
        "logIndex": 0,
        "removed": False,
    },
]
