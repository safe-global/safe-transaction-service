from typing import Dict, List, Union

from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS

from ..models import EthereumEvent


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = BalanceService(EthereumClientProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client

    def get_balances(self, safe_address: str) -> List[Dict[str, Union[str, int]]]:
        """
        :param safe_address:
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert Web3.isChecksumAddress(safe_address), f'Not valid address {safe_address} for getting balances'

        erc20_addresses = list(EthereumEvent.objects.erc20_tokens_used_by_address(safe_address))
        balances = self.ethereum_client.erc20.get_balances(safe_address, erc20_addresses)

        return [balance for balance in balances
                if balance['balance'] > 0 or balance['token_address'] == NULL_ADDRESS]
