def get_eip712_payload_mock():
    address = "0x8e12f01dae5fe7f1122dc42f2cb084f2f9e8aa03"
    types = {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Mailbox": [
            {"name": "owner", "type": "address"},
            {"name": "messages", "type": "Message[]"},
        ],
        "Message": [
            {"name": "sender", "type": "address"},
            {"name": "subject", "type": "string"},
            {"name": "isSpam", "type": "bool"},
            {"name": "body", "type": "string"},
        ],
    }

    msgs = [
        {
            "sender": address,
            "subject": "Hello World",
            "body": "The sparrow flies at midnight.",
            "isSpam": False,
        },
        {
            "sender": address,
            "subject": "You may have already Won! :dumb-emoji:",
            "body": "Click here for sweepstakes!",
            "isSpam": True,
        },
    ]

    mailbox = {"owner": address, "messages": msgs}

    payload = {
        "types": types,
        "primaryType": "Mailbox",
        "domain": {
            "name": "MyDApp",
            "version": "3.0",
            "chainId": 41,
            "verifyingContract": address,
        },
        "message": mailbox,
    }

    return payload
