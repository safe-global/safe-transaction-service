import os

import sha3
from Crypto.Hash import keccak as crypto_keccak
from eth_hash.auto import keccak as eth_hash_keccak
from web3 import Web3


def eth_hash_benchmark() -> str:
    return eth_hash_keccak(os.urandom(32)).hex()


def web3_benchmark() -> str:
    return Web3.keccak(os.urandom(32)).hex()


def cryptodome_benchmark() -> str:
    return crypto_keccak.new(data=os.urandom(32), digest_bits=256).hexdigest()


def pysha3_benchmark() -> str:
    return sha3.keccak_256(os.urandom(32)).hexdigest()


if __name__ == "__main__":
    import timeit

    iterations = 1_000_000

    print(
        "eth_hash",
        timeit.timeit(
            "eth_hash_benchmark()",
            setup="from __main__ import eth_hash_benchmark",
            number=iterations,
            globals=globals(),
        ),
    )
    print(
        "web3",
        timeit.timeit(
            "web3_benchmark()",
            setup="from __main__ import web3_benchmark",
            number=iterations,
            globals=globals(),
        ),
    )
    print(
        "cryptodome",
        timeit.timeit(
            "cryptodome_benchmark()",
            setup="from __main__ import cryptodome_benchmark",
            number=iterations,
            globals=globals(),
        ),
    )
    print(
        "safe-pysha3",
        timeit.timeit(
            "pysha3_benchmark()",
            setup="from __main__ import pysha3_benchmark",
            number=iterations,
            globals=globals(),
        ),
    )
