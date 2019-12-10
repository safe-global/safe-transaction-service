import logging
from typing import Dict, List, Union

import requests
from cachetools import TTLCache, cached

from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.oracles import UniswapOracle, KyberOracle, OracleException

from ..models import EthereumEvent


logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
    pass


class CannotGetEthereumPrice(BalanceServiceException):
    pass


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = BalanceService(EthereumClientProvider(), settings.ETH_UNISWAP_FACTORY_ADDRESS)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient, uniswap_factory_address: str):
        self.ethereum_client = ethereum_client
        self.uniswap_oracle = UniswapOracle(self.ethereum_client.w3, uniswap_factory_address)

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

    @cached(cache=TTLCache(maxsize=1024, ttl=60 * 30))  # 30 minutes of caching
    def get_eth_value(self) -> float:
        # Use kraken for eth_value
        url = 'https://api.kraken.com/0/public/Ticker?pair=ETHUSD'
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get('error')
        if not response.ok or error:
            logger.warning('Cannot get price from url=%s', url)
            raise CannotGetEthereumPrice(str(api_json['error']))

        result = api_json['result']
        for new_ticker in result:
            return float(result[new_ticker]['c'][0])

    @cached(cache=TTLCache(maxsize=1024, ttl=60 * 30))  # 30 minutes of caching
    def get_token_eth_value(self, token_address: str) -> float:
        try:
            self.uniswap_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s', token_address)
            return 0.

    def get_usd_balances(self, safe_address: str) -> List[Dict[str, Union[str, int, float]]]:
        eth_value = self.get_eth_value()
        balances: Dict[str, Union[str, int, float]] = self.get_balances(safe_address)
        for balance in balances:
            token_address = balance['token_address']
            token_to_eth_price = self.get_token_eth_value(token_address)
            balance['balance_usd'] = eth_value * token_to_eth_price
        return balances
