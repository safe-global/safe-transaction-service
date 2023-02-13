import os

import pytest
import requests

from gnosis.eth import EthereumClient

from safe_transaction_service.history.indexers.events_indexer import EventsIndexer


def just_test_if_mainnet_node() -> str:
    mainnet_node_url = os.environ.get("ETHEREUM_MAINNET_NODE")
    if hasattr(just_test_if_mainnet_node, "checked"):  # Just check node first time
        return mainnet_node_url

    if not mainnet_node_url:
        pytest.skip(
            "Mainnet node not defined, cannot test oracles", allow_module_level=True
        )
    else:
        try:
            if not requests.post(
                mainnet_node_url,
                timeout=5,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_blockNumber",
                    "params": [],
                    "id": 1,
                },
            ).ok:
                pytest.skip("Cannot connect to mainnet node", allow_module_level=True)
        except IOError:
            pytest.skip(
                "Problem connecting to the mainnet node", allow_module_level=True
            )
    just_test_if_mainnet_node.checked = True
    return mainnet_node_url


def get_blocks_processed(indexer: EventsIndexer, ethereum_client: EthereumClient):
    from_block_number, _ = indexer.get_block_numbers_for_search(addresses=None)
    current_block_number = ethereum_client.current_block_number
    return current_block_number - from_block_number
