from gnosis.eth import EthereumClientProvider, EthereumNetwork


def get_chain_id() -> int:
    return EthereumClientProvider().get_chain_id()


def get_ethereum_network() -> EthereumNetwork:
    return EthereumNetwork(get_chain_id())
