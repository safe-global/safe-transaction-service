import dataclasses
from typing import List

from eth_typing import ChecksumAddress
from safe_eth.eth import EthereumClient
from safe_eth.eth.contracts import get_safe_V1_4_1_contract
from safe_eth.eth.utils import fast_to_checksum_address
from safe_eth.safe.proxy_factory import ProxyFactoryV141


@dataclasses.dataclass(eq=True, frozen=True)
class DecodedInitCode:
    # UserOperation data
    factory_address: ChecksumAddress
    factory_data: bytes  # Factory call with function identifier
    initializer: bytes  # Initializer passed to ProxyFactory
    # ProxyFactory data
    singleton: ChecksumAddress
    salt_nonce: int
    expected_address: ChecksumAddress  # Expected Safe deployment address
    # Safe creation data
    owners: List[ChecksumAddress]
    threshold: int
    to: ChecksumAddress
    data: bytes
    fallback_handler: ChecksumAddress
    payment_token: ChecksumAddress
    payment: int
    payment_receiver: ChecksumAddress


def decode_init_code(
    init_code: bytes, ethereum_client: EthereumClient
) -> DecodedInitCode:
    """
    Decode data to check for a valid ProxyFactory Safe deployment.

    :param init_code: should be composed of:
      - 20 first bytes with the address of the factory.
      - Call data for the ``Factory``. In the case of the Safe:
        - Call to the ``ProxyFactory``, with the ``initializer``, ``singleton`` and ``saltNonce``
        - The ``ProxyFactory`` then deploys a ``Safe Proxy`` and calls ``setup`` with all the configuration parameters.
    :param ethereum_client:
    :return: Decoded Init Code dataclass
    :raises ValueError: Problem decoding
    """
    factory_address = fast_to_checksum_address(init_code[:20])
    factory_data = init_code[20:]
    proxy_factory = ProxyFactoryV141(factory_address, ethereum_client)
    safe_contract = get_safe_V1_4_1_contract(ethereum_client.w3)
    _, data = proxy_factory.contract.decode_function_input(factory_data)
    initializer = data.pop("initializer")
    _, safe_deployment_data = safe_contract.decode_function_input(initializer)

    singleton = data.pop("_singleton")
    salt_nonce = data.pop("saltNonce")
    expected_address = proxy_factory.calculate_proxy_address(
        singleton, initializer, salt_nonce, chain_specific=False
    )
    return DecodedInitCode(
        factory_address,
        factory_data,
        initializer,
        singleton,
        salt_nonce,
        expected_address,
        *(
            safe_deployment_data[field]
            for field in [
                "_owners",
                "_threshold",
                "to",
                "data",
                "fallbackHandler",
                "paymentToken",
                "payment",
                "paymentReceiver",
            ]
        )
    )
