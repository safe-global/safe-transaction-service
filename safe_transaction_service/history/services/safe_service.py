import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Tuple, Union

from eth_typing import ChecksumAddress
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import (
    get_cpk_factory_contract,
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
)
from gnosis.safe import Safe
from gnosis.safe.exceptions import CannotRetrieveSafeInfoException
from gnosis.safe.safe import SafeInfo

from ..exceptions import NodeConnectionException
from ..models import InternalTx, SafeLastStatus, SafeMasterCopy

logger = logging.getLogger(__name__)


class SafeServiceException(Exception):
    pass


class CannotGetSafeInfoFromBlockchain(SafeServiceException):
    pass


class CannotGetSafeInfoFromDB(SafeServiceException):
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
        if not hasattr(cls, "instance"):
            from django.conf import settings

            ethereum_client = EthereumClientProvider()
            ethereum_tracing_client = (
                EthereumClient(settings.ETHEREUM_TRACING_NODE_URL)
                if settings.ETHEREUM_TRACING_NODE_URL
                else None
            )
            cls.instance = SafeService(ethereum_client, ethereum_tracing_client)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeService:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        ethereum_tracing_client: Optional[EthereumClient],
    ):
        """
        :param ethereum_client: Used for regular RPC calls
        :param ethereum_tracing_client: Used for RPC calls requiring trace methods. It's required to get
            next or previous traces for a given `InternalTx` if not found on database
        """
        self.ethereum_client = ethereum_client
        self.ethereum_tracing_client = ethereum_tracing_client
        dummy_w3 = Web3()  # Not needed, just used to decode contracts
        self.proxy_factory_v1_4_1_contract = get_proxy_factory_V1_4_1_contract(dummy_w3)
        self.proxy_factory_v1_3_0_contract = get_proxy_factory_V1_3_0_contract(dummy_w3)
        self.cpk_proxy_factory_contract = get_cpk_factory_contract(dummy_w3)

    def get_safe_creation_info(self, safe_address: str) -> Optional[SafeCreationInfo]:
        """
        :param safe_address:
        :return: SafeCreation info for the provided ``safe_address``
        """
        try:
            # Get first the actual creation transaction for the safe
            creation_internal_tx = (
                InternalTx.objects.filter(
                    ethereum_tx__status=1  # Ignore Internal Transactions for failed Transactions
                )
                .select_related("ethereum_tx__block")
                .get(contract_address=safe_address)
            )
            creation_ethereum_tx = creation_internal_tx.ethereum_tx

            created_time = creation_ethereum_tx.block.timestamp

            # Get the parent trace for the creation
            # For L2s, `ProxyCreation` event is used to emulate the trace
            parent_internal_tx = self._get_parent_internal_tx(creation_internal_tx)

            creator = (parent_internal_tx or creation_ethereum_tx)._from
            proxy_factory = creation_internal_tx._from

            master_copy: Optional[str] = None
            setup_data: Optional[bytes] = None
            data_tx = parent_internal_tx if parent_internal_tx else creation_ethereum_tx

            # A regular ether transfer could trigger a Safe deployment, so it's not guaranteed that there will be
            # ``data`` for the transaction
            if data_tx.data:
                data = bytes(data_tx.data)
                result = self._decode_proxy_factory(
                    data
                ) or self._decode_cpk_proxy_factory(data)
                if result:
                    master_copy, setup_data = result
            if not (master_copy and setup_data):
                if setup_internal_tx := self._get_next_internal_tx(
                    creation_internal_tx
                ):
                    master_copy = setup_internal_tx.to
                    setup_data = setup_internal_tx.data
        except InternalTx.DoesNotExist:
            return None
        except IOError as exc:
            raise NodeConnectionException from exc

        return SafeCreationInfo(
            created_time,
            creator,
            proxy_factory,
            master_copy,
            setup_data,
            creation_internal_tx.ethereum_tx_id,
        )

    def get_safe_info(self, safe_address: ChecksumAddress) -> SafeInfo:
        """
        :param safe_address:
        :return: SafeInfo for the provided `safe_address`. First tries database, if not
            found or if `nonce=0` it will try blockchain
        :raises: CannotGetSafeInfoFromBlockchain
        """
        try:
            safe_info = self.get_safe_info_from_db(safe_address)
            if safe_info.nonce == 0:
                # This works for:
                # - Not indexed Safes
                # - Not L2 Safes on L2 networks
                raise CannotGetSafeInfoFromDB
            return safe_info
        except CannotGetSafeInfoFromDB:
            return self.get_safe_info_from_blockchain(safe_address)

    def get_safe_info_from_blockchain(self, safe_address: ChecksumAddress) -> SafeInfo:
        """
        :param safe_address:
        :return: SafeInfo from blockchain
        """
        try:
            safe = Safe(safe_address, self.ethereum_client)
            safe_info = safe.retrieve_all_info()
            # Return same master copy information than the db method
            return replace(
                safe_info,
                version=SafeMasterCopy.objects.get_version_for_address(
                    safe_info.master_copy
                ),
            )
        except IOError as exc:
            raise NodeConnectionException from exc
        except CannotRetrieveSafeInfoException as exc:
            raise CannotGetSafeInfoFromBlockchain(safe_address) from exc

    def get_safe_info_from_db(self, safe_address: ChecksumAddress) -> SafeInfo:
        try:
            return SafeLastStatus.objects.get_or_generate(safe_address).get_safe_info()
        except SafeLastStatus.DoesNotExist as exc:
            raise CannotGetSafeInfoFromDB(safe_address) from exc

    def _decode_proxy_factory(
        self, data: Union[bytes, str]
    ) -> Optional[Tuple[str, bytes]]:
        """
        Decode contract creation function for Safe ProxyFactory deployments

        :param data:
        :return: Tuple with the `master_copy` and `setup_data`, `None` if it cannot be decoded
        """
        if not data:
            return None
        try:
            _, data_decoded = self.proxy_factory_v1_3_0_contract.decode_function_input(
                data
            )
        except ValueError:
            try:
                (
                    _,
                    data_decoded,
                ) = self.proxy_factory_v1_4_1_contract.decode_function_input(data)
            except ValueError:
                return None
        master_copy = (
            data_decoded.get("masterCopy")
            or data_decoded.get("_mastercopy")
            or data_decoded.get("_singleton")
            or data_decoded.get("singleton")
        )
        setup_data = data_decoded.get("data") or data_decoded.get("initializer")
        if master_copy and setup_data is not None:
            return master_copy, setup_data

        logger.error("Problem decoding proxy factory, data_decoded=%s", data_decoded)
        return None

    def _decode_cpk_proxy_factory(
        self, data: Union[bytes, str]
    ) -> Optional[Tuple[str, bytes]]:
        """
        Decode contract creation function for Safe Contract Proxy Kit Safe deployments (function is different
        from the regular ProxyFactory)

        More info: https://github.com/5afe/contract-proxy-kit

        :param data:
        :return: Tuple with the `master_copy` and `setup_data`, `None` if it cannot be decoded
        """
        if not data:
            return None
        try:
            _, data_decoded = self.cpk_proxy_factory_contract.decode_function_input(
                data
            )
            master_copy = data_decoded.get("masterCopy")
            setup_data = data_decoded.get("data")
            return master_copy, setup_data
        except ValueError:
            return None

    def _get_next_internal_tx(self, internal_tx: InternalTx) -> Optional[InternalTx]:
        if child_trace := internal_tx.get_child(0):
            return child_trace
        if not self.ethereum_tracing_client:
            return None
        try:
            next_traces = self.ethereum_tracing_client.tracing.get_next_traces(
                internal_tx.ethereum_tx_id,
                internal_tx.trace_address_as_list,
                remove_calls=True,
            )
            return next_traces and InternalTx.objects.build_from_trace(
                next_traces[0], internal_tx.ethereum_tx
            )
        except ValueError:
            return None

    def _get_parent_internal_tx(self, internal_tx: InternalTx) -> InternalTx:
        if parent_trace := internal_tx.get_parent():
            return parent_trace
        if not self.ethereum_tracing_client:
            return None
        try:
            previous_trace = self.ethereum_tracing_client.tracing.get_previous_trace(
                internal_tx.ethereum_tx_id,
                internal_tx.trace_address_as_list,
                skip_delegate_calls=True,
            )
            return previous_trace and InternalTx.objects.build_from_trace(
                previous_trace, internal_tx.ethereum_tx
            )
        except ValueError:
            return None
