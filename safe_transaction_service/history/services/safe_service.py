import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, Union

from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import (get_cpk_factory_contract,
                                  get_proxy_factory_contract)
from gnosis.safe import Safe
from gnosis.safe.exceptions import CannotRetrieveSafeInfoException
from gnosis.safe.safe import SafeInfo

from ..models import InternalTx

logger = logging.getLogger(__name__)


class SafeServiceException(Exception):
    pass


class CannotGetSafeInfo(SafeServiceException):
    pass


EthereumAddress = str


@dataclass
class SafeCreationInfo:
    created: datetime
    creator: EthereumAddress
    factory_address: EthereumAddress
    master_copy: Optional[EthereumAddress]
    setup_data: Optional[bytes]
    transaction_hash: str


class SafeServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeService(EthereumClientProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, 'instance'):
            del cls.instance


class SafeService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        dummy_w3 = Web3()  # Not needed, just used to decode contracts
        self.proxy_factory_contract = get_proxy_factory_contract(dummy_w3)
        self.cpk_proxy_factory_contract = get_cpk_factory_contract(dummy_w3)

    def get_safe_creation_info(self, safe_address: str) -> Optional[SafeCreationInfo]:
        try:
            creation_internal_tx = InternalTx.objects.filter(
                ethereum_tx__status=1  # Ignore Internal Transactions for failed Transactions
            ).select_related('ethereum_tx__block').get(contract_address=safe_address)

            previous_internal_tx = creation_internal_tx.get_previous_trace()
            created = creation_internal_tx.ethereum_tx.block.timestamp
            creator = (previous_internal_tx or creation_internal_tx)._from
            proxy_factory = creation_internal_tx._from

            master_copy = None
            setup_data = None
            if previous_internal_tx:
                data = previous_internal_tx.data.tobytes()
                result = self._decode_proxy_factory(data) or self._decode_cpk_proxy_factory(data)
                if result:
                    master_copy, setup_data = result
        except InternalTx.DoesNotExist:
            return None

        return SafeCreationInfo(created, creator, proxy_factory, master_copy, setup_data,
                                creation_internal_tx.ethereum_tx_id)

    def get_safe_info(self, safe_address: str) -> SafeInfo:
        try:
            safe = Safe(safe_address, self.ethereum_client)
            return safe.retrieve_all_info()
        except CannotRetrieveSafeInfoException as e:
            raise CannotGetSafeInfo from e

    def _decode_proxy_factory(self, data: Union[bytes, str]) -> Optional[Tuple[str, bytes]]:
        try:
            _, decoded_data = self.proxy_factory_contract.decode_function_input(data)
            master_copy = decoded_data.get('masterCopy', decoded_data.get('_mastercopy'))
            setup_data = decoded_data.get('data', decoded_data.get('initializer'))
            return master_copy, setup_data
        except ValueError:
            return None

    def _decode_cpk_proxy_factory(self, data) -> Optional[Tuple[str, bytes]]:
        try:
            _, decoded_data = self.cpk_proxy_factory_contract.decode_function_input(data)
            master_copy = decoded_data.get('masterCopy')
            setup_data = decoded_data.get('data')
            return master_copy, setup_data
        except ValueError:
            return None
