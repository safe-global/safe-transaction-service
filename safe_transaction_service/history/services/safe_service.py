import logging
import operator
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import get_proxy_factory_contract

from ..models import InternalTx

logger = logging.getLogger(__name__)


class SafeServiceException(Exception):
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
        if hasattr(cls, "instance"):
            del cls.instance


class SafeService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client

    def get_safe_creation_info(self, safe_address: str) -> Optional[SafeCreationInfo]:
        try:
            creation_internal_tx = InternalTx.objects.select_related('ethereum_tx__block'
                                                                     ).get(contract_address=safe_address)
            previous_internal_tx = creation_internal_tx.get_previous_trace()
            created = creation_internal_tx.ethereum_tx.block.timestamp
            creator = (previous_internal_tx or creation_internal_tx)._from
            proxy_factory = creation_internal_tx._from

            master_copy = None
            setup_data = None
            if previous_internal_tx:
                try:
                    data = previous_internal_tx.data.tobytes()
                    _, decoded_data = get_proxy_factory_contract(Web3()).decode_function_input(data)
                    master_copy = decoded_data.get('masterCopy', decoded_data.get('_mastercopy'))
                    setup_data = decoded_data.get('data', decoded_data.get('initializer'))
                except ValueError:
                    pass
        except InternalTx.DoesNotExist:
            return None

        return SafeCreationInfo(created, creator, proxy_factory, master_copy, setup_data,
                                creation_internal_tx.ethereum_tx_id)
