from safe_eth.eth import EthereumNetwork, get_auto_ethereum_client


def get_chain_id() -> int:
    return get_auto_ethereum_client().get_chain_id()


def get_ethereum_network() -> EthereumNetwork:
    return EthereumNetwork(get_chain_id())
