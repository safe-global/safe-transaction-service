from functools import cache

from gnosis.eth import EthereumClientProvider, EthereumNetwork


@cache
def get_ethereum_network() -> EthereumNetwork:
    return EthereumClientProvider().get_network()
