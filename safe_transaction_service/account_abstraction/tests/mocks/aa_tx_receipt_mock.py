from hexbytes import HexBytes

aa_chain_id = 11155111

aa_safe_address = "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861"

aa_expected_user_operation_hash = HexBytes(
    "0x39b3e2171c04539d9b3f848d04364dfaa42cc0b412ff65ce2a85c566cf8bf281"
)
aa_expected_safe_operation_hash = HexBytes(
    "0xb34556b3564ad04e472ca0f846afe44e0cfff8ceb0f94302792fdd1b9aff1351"
)


aa_tx_receipt_mock = {
    "blockHash": HexBytes(
        "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
    ),
    "blockNumber": 5288154,
    "contractAddress": None,
    "cumulativeGasUsed": 13804372,
    "effectiveGasPrice": 176552365,
    "from": "0xd53Eb5203e367BbDD4f72338938224881Fc501Ab",
    "gasUsed": 424992,
    "logs": [
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0xecdf3a3effea5783a3c4c2140e677577666428d44ed9d474a0b3a4c9943f8440"
                ),
                HexBytes(
                    "0x000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b4037"
                ),
            ],
            "data": HexBytes("0x"),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 194,
            "removed": False,
        },
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0x141df868a6331af528e38c83b7aa03edc19be66e37ae67f9285bf4f8e3c6a1a8"
                ),
                HexBytes(
                    "0x0000000000000000000000004e1dcf7ad4e460cfd30791ccc4f9c8a4f820ec67"
                ),
            ],
            "data": HexBytes(
                "0x000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000010000000000000000000000008ecd4ec46d4d2a6b64fe960b3d64e8b94b2234eb000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b403700000000000000000000000000000000000000000000000000000000000000010000000000000000000000005ac255889882acd3da2aa939679e3f3d4cea221e"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 195,
            "removed": False,
        },
        {
            "address": "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67",
            "topics": [
                HexBytes(
                    "0x4f51faf6c4561ff95f067657e43439f0f856d97c04d9ec9070a6199ad418e235"
                ),
                HexBytes(
                    "0x000000000000000000000000b0b5c0578aa134b0496a6c0e51a7aae47c522861"
                ),
            ],
            "data": HexBytes(
                "0x00000000000000000000000029fcb43b46531bca003ddc8fcb67ffe91900c762"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 196,
            "removed": False,
        },
        {
            "address": "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
            "topics": [
                HexBytes(
                    "0xd51a9c61267aa6196961883ecf5ff2da6619c37dac0fa92122513fb32c032d2d"
                ),
                HexBytes(
                    "0x39b3e2171c04539d9b3f848d04364dfaa42cc0b412ff65ce2a85c566cf8bf281"
                ),
                HexBytes(
                    "0x000000000000000000000000b0b5c0578aa134b0496a6c0e51a7aae47c522861"
                ),
            ],
            "data": HexBytes(
                "0x0000000000000000000000004e1dcf7ad4e460cfd30791ccc4f9c8a4f820ec670000000000000000000000000000000000000000000000000000000000000000"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 197,
            "removed": False,
        },
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0xb648d3644f584ed1c2232d53c46d87e693586486ad0d1175f8656013110b714e"
                )
            ],
            "data": HexBytes(
                "0x000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b40370000000000000000000000005ff137d4b0fdcd49dca30c7cf57e578a026d27890000000000000000000000000000000000000000000000000002b32962c0bb8400000000000000000000000000000000000000000000000000000000000000a000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 198,
            "removed": False,
        },
        {
            "address": "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
            "topics": [
                HexBytes(
                    "0x2da466a7b24304f47e87fa2e1e5a81b9831ce54fec19055ce277ca2f39ba42c4"
                ),
                HexBytes(
                    "0x000000000000000000000000b0b5c0578aa134b0496a6c0e51a7aae47c522861"
                ),
            ],
            "data": HexBytes(
                "0x0000000000000000000000000000000000000000000000000002b32962c0bb84"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 199,
            "removed": False,
        },
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0x6895c13664aa4f67288b25d7a21d7aaa34916e355fb9b6fae0a139a9085becb8"
                ),
                HexBytes(
                    "0x000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b4037"
                ),
            ],
            "data": HexBytes("0x"),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 200,
            "removed": False,
        },
        {
            "address": "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
            "topics": [
                HexBytes(
                    "0xbb47ee3e183a558b1a2ff0874b079f3fc5478b7454eacf2bfc5af2ff5878f972"
                )
            ],
            "data": HexBytes("0x"),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 201,
            "removed": False,
        },
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0xb648d3644f584ed1c2232d53c46d87e693586486ad0d1175f8656013110b714e"
                )
            ],
            "data": HexBytes(
                "0x000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b403700000000000000000000000002270bd144e70ce6963ba02f575776a16184e1e600000000000000000000000000000000000000000000000000005af3107a400000000000000000000000000000000000000000000000000000000000000000a000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 202,
            "removed": False,
        },
        {
            "address": "0xB0B5c0578Aa134b0496a6C0e51A7aae47C522861",
            "topics": [
                HexBytes(
                    "0x6895c13664aa4f67288b25d7a21d7aaa34916e355fb9b6fae0a139a9085becb8"
                ),
                HexBytes(
                    "0x000000000000000000000000a581c4a4db7175302464ff3c06380bc3270b4037"
                ),
            ],
            "data": HexBytes("0x"),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 203,
            "removed": False,
        },
        {
            "address": "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
            "topics": [
                HexBytes(
                    "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"
                ),
                HexBytes(
                    "0x39b3e2171c04539d9b3f848d04364dfaa42cc0b412ff65ce2a85c566cf8bf281"
                ),
                HexBytes(
                    "0x000000000000000000000000b0b5c0578aa134b0496a6c0e51a7aae47c522861"
                ),
                HexBytes(
                    "0x0000000000000000000000000000000000000000000000000000000000000000"
                ),
            ],
            "data": HexBytes(
                "0x000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000001c7f432341e240000000000000000000000000000000000000000000000000000000000068072"
            ),
            "blockNumber": 5288154,
            "transactionHash": HexBytes(
                "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
            ),
            "transactionIndex": 133,
            "blockHash": HexBytes(
                "0xcc466b284f4030ee3f5941a2c8e36892262bf583611c902fe5558a595af47e13"
            ),
            "logIndex": 204,
            "removed": False,
        },
    ],
    "logsBloom": HexBytes(
        "0x080004000000900000000000000000008000000000000000000000000200000000080000000000000002200100000000001000000000000080000200000000000000100000000000000000000000000000000000000004080040000000002000000000000a00000005000000000008000000000001000000000000000002000008000120204002000000000000400000000002000004000000000000000000000000000000000010005000000000000002000000000000000000020000000000000000000000000000010000000000000000000000200000000000000000200000400c0000010000000000000008100220000000000000080000000000000000"
    ),
    "status": 1,
    "to": "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
    "transactionHash": HexBytes(
        "0xf8dab30ed3c8814ee9a67770ee68f8fb83e6247706c24371a76e7cd8d348b0e3"
    ),
    "transactionIndex": 133,
    "type": 2,
}
