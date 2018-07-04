import os
from random import randint

from ethereum import utils


def get_eth_address_with_key() -> (str, bytes):

    # import secp256k1
    # private_key = secp256k1.PrivateKey().private_key

    private_key = utils.sha3(os.urandom(4096))

    public_key = utils.checksum_encode(utils.privtoaddr(private_key))

    # If you want to use secp256k1 to calculate public_key
    # utils.checksum_encode(utils.sha3(p.pubkey.serialize(compressed=False)[1:])[-20:])

    return (public_key,
            private_key)


def get_eth_address_with_invalid_checksum() -> str:
    address, _ = get_eth_address_with_key()
    return '0x' + ''.join([c.lower() if c.isupper() else c.upper() for c in address[2:]])


def get_transaction_with_info(sender=None, recipient=None, data=b'') -> (str, dict):
    sender, _ = get_eth_address_with_key()
    recipient, _ = get_eth_address_with_key()

    transaction_data = {
        'from': sender,
        'to': recipient,
        'data': data,
        'value': randint(0, 100),
        'nonce': randint(0, 100)
    }

    transaction_hash = utils.sha3(transaction_data)
    return transaction_hash.hex(), transaction_data
