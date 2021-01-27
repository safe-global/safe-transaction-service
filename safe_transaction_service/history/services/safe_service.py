import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, Union

from web3 import Web3

from gnosis.eth import EthereumClient
from gnosis.eth.contracts import (get_cpk_factory_contract,
                                  get_proxy_factory_contract)
from gnosis.safe import Safe
from gnosis.safe.exceptions import CannotRetrieveSafeInfoException
from gnosis.safe.safe import SafeInfo

from ..exceptions import NodeConnectionError
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
            from django.conf import settings
            cls.instance = SafeService(EthereumClient(settings.ETHEREUM_TRACING_NODE_URL))
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

            previous_internal_tx = self._get_previous_internal_tx(creation_internal_tx)

            created = creation_internal_tx.ethereum_tx.block.timestamp
            creator = (previous_internal_tx or creation_internal_tx)._from
            proxy_factory = creation_internal_tx._from

            master_copy: Optional[str] = None
            setup_data: Optional[bytes] = None
            if previous_internal_tx:
                data = previous_internal_tx.data
                result = self._decode_proxy_factory(data) or self._decode_cpk_proxy_factory(data)
                if result:
                    master_copy, setup_data = result
            if not (master_copy and setup_data):
                if next_internal_tx := self._get_next_internal_tx(creation_internal_tx):
                    master_copy = next_internal_tx.to
                    setup_data = next_internal_tx.data
        except InternalTx.DoesNotExist:
            return None
        except IOError as exc:
            raise NodeConnectionError from exc

        return SafeCreationInfo(created, creator, proxy_factory, master_copy, setup_data,
                                creation_internal_tx.ethereum_tx_id)

    def get_safe_info(self, safe_address: str) -> SafeInfo:
        try:
            safe = Safe(safe_address, self.ethereum_client)
            return safe.retrieve_all_info()
        except IOError as exc:
            raise NodeConnectionError from exc
        except CannotRetrieveSafeInfoException as e:
            raise CannotGetSafeInfo from e

    def _decode_proxy_factory(self, data: Union[bytes, str]) -> Optional[Tuple[str, bytes]]:
        try:
            _, data_decoded = self.proxy_factory_contract.decode_function_input(data)
            master_copy = data_decoded.get('masterCopy', data_decoded.get('_mastercopy'))
            setup_data = data_decoded.get('data', data_decoded.get('initializer'))
            return master_copy, setup_data
        except ValueError:
            return None

    def _decode_cpk_proxy_factory(self, data: Union[bytes, str]) -> Optional[Tuple[str, bytes]]:
        try:
            _, data_decoded = self.cpk_proxy_factory_contract.decode_function_input(data)
            master_copy = data_decoded.get('masterCopy')
            setup_data = data_decoded.get('data')
            return master_copy, setup_data
        except ValueError:
            return None

    def _get_next_internal_tx(self, internal_tx: InternalTx):
        next_traces = self.ethereum_client.parity.get_next_traces(internal_tx.ethereum_tx_id,
                                                                  internal_tx.trace_address_as_list,
                                                                  remove_calls=True)
        return next_traces and InternalTx.objects.build_from_trace(next_traces[0],
                                                                   internal_tx.ethereum_tx)

    def _get_previous_internal_tx(self, internal_tx: InternalTx):
        previous_trace = self.ethereum_client.parity.get_previous_trace(internal_tx.ethereum_tx_id,
                                                                        internal_tx.trace_address_as_list,
                                                                        skip_delegate_calls=True)
        return previous_trace and InternalTx.objects.build_from_trace(previous_trace,
                                                                      internal_tx.ethereum_tx)
