import functools
import os

import pytest
import requests


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


def skip_on(exception, reason="Test skipped due to a controlled exception"):
    """
    Decorator to skip a test if an exception is raised instead of failing it

    :param exception:
    :param reason:
    :return:
    """

    def decorator_func(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                # Run the test
                return f(*args, **kwargs)
            except exception:
                pytest.skip(reason)

        return wrapper

    return decorator_func
