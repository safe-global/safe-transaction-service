import os

import pytest
import requests


def just_test_if_mainnet_node() -> str:
    mainnet_node_url = os.environ.get('ETHEREUM_MAINNET_NODE')
    if not mainnet_node_url:
        pytest.skip("Mainnet node not defined, cannot test oracles", allow_module_level=True)
    elif requests.get(mainnet_node_url).status_code == 404:
        pytest.skip("Cannot connect to mainnet node", allow_module_level=True)
    return mainnet_node_url
