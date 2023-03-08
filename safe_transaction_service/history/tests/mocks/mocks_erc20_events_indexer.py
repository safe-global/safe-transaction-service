from hexbytes import HexBytes

log_receipt_mock = [
    {
        "address": "0xD84dbd5138D2297959Ae56602Bd5B2A035bb3F59",
        "blockHash": HexBytes(
            "0xe630ebf8c8ff2397896f23de27fd6e9f280d4ede613acbf788d545cc0c5194e8"
        ),
        "blockNumber": 6,
        "data": "0x000000000000000000000000000000000000000000000000000000000000000a",
        "logIndex": 0,
        "removed": False,
        "topics": [
            HexBytes(
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
            ),
            HexBytes(
                "0x00000000000000000000000022d491bde2303f2f43325b2108d26f1eaba1e32b"
            ),
            HexBytes(
                "0x0000000000000000000000006e5b7093ac36ea61da02fd1cceecf56fd6626d48"
            ),
        ],
        "transactionHash": HexBytes(
            "0x53a869a24855dcae97e6cea9069eb7a2e57c45a3538081947a1af7a7da38d627"
        ),
        "transactionIndex": 0,
        "args": {
            "from": "0x22d491Bde2303f2f43325b2108D26f1eAbA1e32b",
            "to": "0x6e5B7093aC36EA61da02Fd1CcEeCF56fD6626D48",
            "value": 10,
        },
    }
]
