import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from eth_typing import ChecksumAddress
from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.eth.contracts import (
    get_cpk_factory_contract,
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
)
from safe_eth.safe import Safe
from safe_eth.safe.exceptions import CannotRetrieveSafeInfoException
from safe_eth.safe.multi_send import MultiSend
from safe_eth.safe.safe import SafeInfo
from web3 import Web3

from safe_transaction_service.account_abstraction import models as aa_models
from safe_transaction_service.utils.abis.gelato import gelato_relay_1_balance_v2_abi

from ..exceptions import NodeConnectionException
from ..models import (
    EthereumTx,
    InternalTx,
    InternalTxType,
    SafeLastStatus,
    SafeMasterCopy,
)

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
    salt_nonce: Optional[int]
    transaction_hash: str
    user_operation: Optional[aa_models.UserOperation]


@dataclass
class ProxyCreationData:
    singleton: ChecksumAddress
    initializer: bytes
    salt_nonce: Optional[int]


class SafeServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            ethereum_client = get_auto_ethereum_client()
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
        self.gelato_relay_1_balance_v2_contract = dummy_w3.eth.contract(
            abi=gelato_relay_1_balance_v2_abi
        )
        self.proxy_creation_event_topic = event_abi_to_log_topic(
            self.proxy_factory_v1_4_1_contract.events.ProxyCreation().abi
        )

    def get_safe_creation_info(
        self, safe_address: ChecksumAddress
    ) -> Optional[SafeCreationInfo]:
        """
        :param safe_address:
        :return: SafeCreation info for the provided ``safe_address``
        """
        try:
            # Get first the actual creation transaction for the safe
            creation_internal_tx = (
                InternalTx.objects.filter(
                    ethereum_tx__status=1,  # Ignore Internal Transactions for failed Transactions
                    tx_type=InternalTxType.CREATE.value,
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

            singleton: Optional[str] = None
            initializer: Optional[bytes] = None
            salt_nonce: Optional[int] = None

            # For L2s, as traces are "simulated", they don't hold `data` and creation ethereum_tx must be used
            data_tx = parent_internal_tx if parent_internal_tx else creation_ethereum_tx

            # A regular ether transfer could trigger a Safe deployment, so it's not guaranteed that there will be
            # ``data`` for the transaction
            proxy_creation_data = (
                self._process_creation_data(
                    safe_address, HexBytes(data_tx.data), creation_ethereum_tx
                )
                if data_tx.data
                else None
            )

            if proxy_creation_data:
                singleton = proxy_creation_data.singleton
                initializer = proxy_creation_data.initializer
                salt_nonce = proxy_creation_data.salt_nonce
            if not (singleton and initializer):
                if setup_internal_tx := self._get_next_internal_tx(
                    creation_internal_tx
                ):
                    singleton = setup_internal_tx.to
                    initializer = setup_internal_tx.data
        except InternalTx.DoesNotExist:
            return None
        except IOError as exc:
            raise NodeConnectionException from exc

        user_operation = (
            aa_models.UserOperation.objects.filter(
                ethereum_tx=creation_ethereum_tx,
                sender=safe_address,
            )
            .exclude(init_code=None)
            .select_related("receipt", "safe_operation")
            .prefetch_related("safe_operation__confirmations")
            .first()
        )
        return SafeCreationInfo(
            created_time,
            creator,
            proxy_factory,
            singleton,
            initializer,
            salt_nonce,
            creation_internal_tx.ethereum_tx_id,
            user_operation,
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

    def _process_creation_data(
        self,
        safe_address: ChecksumAddress,
        data: bytes,
        ethereum_tx: EthereumTx,
    ) -> Optional[ProxyCreationData]:
        """
        Process creation data and return the proper one for the provided Safe, as for L2s multiple deployments
        can be present in the data, so we need to check the events and match them with the decoded data.

        :param data:
        :return: ProxyCreationData for the provided Safe
        """

        proxy_creation_data_list = self._decode_creation_data(data)

        if not proxy_creation_data_list:
            return None

        if len(proxy_creation_data_list) == 1:
            return proxy_creation_data_list[0]

        # If there are more than one deployment, we need to know which one is the one we need
        deployed_safes = ethereum_tx.get_deployed_proxies_from_logs()
        if len(deployed_safes) == len(proxy_creation_data_list):
            for deployed_safe, proxy_creation_data in zip(
                deployed_safes, proxy_creation_data_list
            ):
                if safe_address == deployed_safe:
                    return proxy_creation_data

        logger.warning(
            "[%s] Proxy creation data is not matching the proxies deployed %s",
            safe_address,
            deployed_safes,
        )
        return None

    def _decode_creation_data(self, data: bytes) -> list[ProxyCreationData]:
        """
        Decode creation data for Safe ProxyFactory deployments.

        For L1 networks the trace is present, so no need for `MultiSend` or `Gelato Relay` decoding. At much one
        `ProxyCreationData` will be returned.

        For L2 networks the data for the whole transaction will be decoded, so an approximation must
        be done to find the function parameters. There could be more than one `ProxyCreationData` when
        deploying Safes via contracts like `MultiSend`. `MultiSend` and `Gelato Relay` transactions are supported.

        :return: `ProxyCreationData`, `None` if it cannot be decoded
        """
        if not data:
            return []

        # Try to decode using Gelato Relayer (relayer must be the first call)
        data = self._decode_gelato_relay(data)

        # Try to decode using MultiSend. If not, take the original data
        multisend_data = [
            multisend_tx.data for multisend_tx in MultiSend.from_transaction_data(data)
        ] or [data]
        results = []
        for data in multisend_data:
            result = self._decode_proxy_factory(data) or self._decode_cpk_proxy_factory(
                data
            )
            if result:
                results.append(result)
        return results

    def _decode_gelato_relay(self, data: bytes) -> bytes:
        """
        Try to decode transaction for Gelato Relayer

        :param data:
        :return: Decoded `data` if possible, original `data` otherwise
        """
        try:
            _, decoded_gelato_data = (
                self.gelato_relay_1_balance_v2_contract.decode_function_input(data)
            )
            return HexBytes(decoded_gelato_data["_data"])
        except ValueError:
            return data

    def _decode_proxy_factory(self, data: bytes) -> Optional[ProxyCreationData]:
        """
        Decode contract creation function for Safe ProxyFactory 1.3.0 and 1.4.1 deployments

        :param data:
        :return: `ProxyCreationData`, `None` if it cannot be decoded
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

        singleton = (
            data_decoded.get("masterCopy")
            or data_decoded.get("_mastercopy")
            or data_decoded.get("_singleton")
            or data_decoded.get("singleton")
        )
        initializer = data_decoded.get("data") or data_decoded.get("initializer")
        salt_nonce = data_decoded.get("saltNonce")
        if singleton is not None and initializer is not None:
            return ProxyCreationData(singleton, initializer, salt_nonce)

        logger.error("Problem decoding proxy factory, data_decoded=%s", data_decoded)
        return None

    def _decode_cpk_proxy_factory(self, data: bytes) -> Optional[ProxyCreationData]:
        """
        Decode contract creation function for Safe Contract Proxy Kit Safe deployments (function is different
        from the regular ProxyFactory)

        More info: https://github.com/5afe/contract-proxy-kit

        :param data:
        :return: `ProxyCreationData`, `None` if it cannot be decoded
        """
        if not data:
            return None
        try:
            _, data_decoded = self.cpk_proxy_factory_contract.decode_function_input(
                data
            )
            master_copy = data_decoded.get("masterCopy")
            setup_data = data_decoded.get("data")
            salt_nonce = data_decoded.get("saltNonce")
            return ProxyCreationData(master_copy, setup_data, salt_nonce)
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

    def _get_parent_internal_tx(self, internal_tx: InternalTx) -> Optional[InternalTx]:
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
