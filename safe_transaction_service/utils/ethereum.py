from functools import cache

from gnosis.eth import EthereumClientProvider, EthereumNetwork


@cache
def get_chain_id() -> int:
    return EthereumClientProvider().get_chain_id()


def get_ethereum_network() -> EthereumNetwork:
    return EthereumNetwork(get_chain_id())
