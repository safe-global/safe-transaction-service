import logging
from typing import Dict, List, Optional, Union

import requests
from cachetools import TTLCache, cached
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import get_erc20_contract
from gnosis.eth.oracles import OracleException, UniswapOracle

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
        self.token_decimals = {}

    def get_balances(self, safe_address: str) -> List[Dict[str, Union[str, int]]]:
        """
        :param safe_address:
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert Web3.isChecksumAddress(safe_address), f'Not valid address {safe_address} for getting balances'

        erc20_addresses = list(EthereumEvent.objects.erc20_tokens_used_by_address(safe_address))
        balances = self.ethereum_client.erc20.get_balances(safe_address, erc20_addresses)

        return [balance for balance in balances
                if balance['balance'] > 0 or not balance['token_address']]

    @cached(cache=TTLCache(maxsize=1024, ttl=60 * 30))  # 30 minutes of caching
    def get_eth_usd_price(self) -> float:
        """
        Return current USD price for ethereum
        """
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
        """
        Return current ether value for a given `token_address`
        """
        try:
            return self.uniswap_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s', token_address)
            return 0.
        except ValueError:
            logger.warning('VM execution error getting eth value for token-address=%s', token_address, exc_info=True)
            return 0.

    def get_token_decimals(self, token_address: Optional[str]) -> int:
        if not token_address:
            return 18  # Ether
        if token_address not in self.token_decimals:
            erc20_contract = get_erc20_contract(self.ethereum_client.w3, token_address)
            self.token_decimals[token_address] = erc20_contract.functions.decimals().call()
        return self.token_decimals[token_address]

    def get_usd_balances(self, safe_address: str) -> List[Dict[str, Union[str, int, float]]]:
        """
        All this could be more optimal (e.g. batching requests), but as everything is cached
        I think we should be alright
        """
        balances: Dict[str, Union[str, int, float]] = self.get_balances(safe_address)
        eth_value = self.get_eth_usd_price()
        for balance in balances:
            token_address = balance['token_address']
            if not token_address:  # Ether
                balance['balance_usd'] = eth_value * (balance['balance'] / 18)
            else:
                token_to_eth_price = self.get_token_eth_value(token_address)
                if token_to_eth_price:
                    balance_with_decimals = balance['balance'] / self.get_token_decimals(token_address)
                    balance['balance_usd'] = eth_value * token_to_eth_price * balance_with_decimals
                else:
                    balance['balance_usd'] = 0
        return balances
