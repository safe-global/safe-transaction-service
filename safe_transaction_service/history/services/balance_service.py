import logging
import operator
from dataclasses import asdict, dataclass
from typing import List, Optional

import requests
from cachetools import TTLCache, cached, cachedmethod
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.ethereum_client import Erc20Info, InvalidERC20Info
from gnosis.eth.oracles import KyberOracle, OracleException, UniswapOracle

from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
    pass


class CannotGetEthereumPrice(BalanceServiceException):
    pass


@dataclass
class Balance:
    token_address: Optional[str]
    token: Optional[Erc20Info]
    balance: int


@dataclass
class BalanceWithUsd(Balance):
    balance_usd: float


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = BalanceService(EthereumClientProvider(), settings.ETH_UNISWAP_FACTORY_ADDRESS,
                                          settings.ETH_KYBER_NETWORK_PROXY_ADDRESS)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient,
                 uniswap_factory_address: str, kyber_network_proxy_address: str):
        self.ethereum_client = ethereum_client
        self.uniswap_oracle = UniswapOracle(self.ethereum_client, uniswap_factory_address)
        self.kyber_oracle = KyberOracle(self.ethereum_client, kyber_network_proxy_address)
        self.token_info_cache = {}

    def get_balances(self, safe_address: str) -> List[Balance]:
        """
        :param safe_address:
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert Web3.isChecksumAddress(safe_address), f'Not valid address {safe_address} for getting balances'

        erc20_addresses = list(EthereumEvent.objects.erc20_tokens_used_by_address(safe_address))
        raw_balances = self.ethereum_client.erc20.get_balances(safe_address, erc20_addresses)

        balances = []
        for balance in raw_balances:
            if not balance['token_address']:  # Ether
                balance['token'] = None
            elif balance['balance'] > 0:
                balance['token'] = self.get_token_info(balance['token_address'])
                if not balance['token']:  # Ignore ERC20 tokens that cannot be queried
                    continue
            else:
                continue
            balances.append(Balance(**balance))
        return balances

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
            logger.warning('Cannot get eth value for token-address=%s on uniswap, trying Kyber', token_address)

        try:
            return self.kyber_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s from Kyber', token_address)
            return 0.

    @cachedmethod(cache=operator.attrgetter('token_info_cache'))
    def get_token_info(self, token_address: str) -> Optional[Erc20Info]:
        try:
            return self.ethereum_client.erc20.get_info(token_address)
        except InvalidERC20Info:
            logger.warning('Cannot get token info for token-address=%s', token_address)
            return None

    def get_usd_balances(self, safe_address: str) -> List[BalanceWithUsd]:
        """
        All this could be more optimal (e.g. batching requests), but as everything is cached
        I think we should be alright
        """
        balances: List[Balance] = self.get_balances(safe_address)
        eth_value = self.get_eth_usd_price()
        balances_with_usd = []
        for balance in balances:
            token_address = balance.token_address
            if not token_address:  # Ether
                balance_usd = eth_value * (balance.balance / 10**18)
            else:
                token_to_eth_price = self.get_token_eth_value(token_address)
                if token_to_eth_price:
                    balance_with_decimals = balance.balance / 10**balance.token.decimals
                    balance_usd = eth_value * token_to_eth_price * balance_with_decimals
                else:
                    balance_usd = 0.

            balance_dict = asdict(balance)
            balance_dict['balance_usd'] = round(balance_usd, 4)
            balances_with_usd.append(BalanceWithUsd(**balance_dict))

        return balances_with_usd
