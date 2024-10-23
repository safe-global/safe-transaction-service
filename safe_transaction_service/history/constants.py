from eth_utils import event_abi_to_log_topic
from safe_eth.eth.contracts import get_proxy_factory_V1_4_1_contract
from web3 import Web3

SAFE_PROXY_FACTORY_CREATION_EVENT_TOPIC = event_abi_to_log_topic(
    get_proxy_factory_V1_4_1_contract(Web3()).events.ProxyCreation().abi
)
