import itertools
import operator
from functools import cache, cached_property
from logging import getLogger
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    Union,
    cast,
)

import gevent
from cachetools import TTLCache, cachedmethod
from eth_abi import decode as decode_abi
from eth_abi.exceptions import DecodingError
from eth_typing import ChecksumAddress, HexStr
from eth_utils import function_abi_to_4byte_selector
from hexbytes import HexBytes
from web3 import Web3
from web3._utils.abi import get_abi_input_names, get_abi_input_types, map_abi_data
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.contract import Contract
from web3.types import ABIFunction

from gnosis.eth.contracts import (
    get_erc20_contract,
    get_erc721_contract,
    get_kyber_network_proxy_contract,
    get_multi_send_contract,
    get_safe_V0_0_1_contract,
    get_safe_V1_0_0_contract,
    get_safe_V1_1_1_contract,
    get_safe_V1_3_0_contract,
    get_safe_V1_4_1_contract,
    get_uniswap_exchange_contract,
)
from gnosis.safe.multi_send import MultiSend

from safe_transaction_service.contracts.models import ContractAbi
from safe_transaction_service.utils.utils import running_on_gevent

from .decoder_abis.aave import (
    aave_a_token,
    aave_lending_pool,
    aave_lending_pool_addresses_provider,
    aave_lending_pool_core,
)
from .decoder_abis.admin_upgradeability_proxy import (
    initializable_admin_upgradeability_proxy_abi,
)
from .decoder_abis.balancer import balancer_bactions, balancer_exchange_proxy
from .decoder_abis.chainlink import chainlink_token_abi
from .decoder_abis.compound import comptroller_abi, ctoken_abi
from .decoder_abis.gnosis_protocol import (
    fleet_factory_abi,
    fleet_factory_deterministic_abi,
    gnosis_protocol_abi,
)
from .decoder_abis.gnosis_safe import gnosis_safe_allowance_module_abi
from .decoder_abis.idle import idle_token_v3
from .decoder_abis.maker_dao import maker_dao_abis
from .decoder_abis.open_zeppelin import (
    open_zeppelin_admin_upgradeability_proxy,
    open_zeppelin_proxy_admin,
)
from .decoder_abis.request import (
    request_erc20_proxy,
    request_erc20_swap_to_pay,
    request_ethereum_proxy,
)
from .decoder_abis.sablier import sablier_abi, sablier_ctoken_manager, sablier_payroll
from .decoder_abis.sight import (
    conditional_token_abi,
    market_maker_abi,
    market_maker_factory_abi,
)
from .decoder_abis.snapshot import snapshot_delegate_registry_abi
from .decoder_abis.timelock import timelock_abi

logger = getLogger(__name__)


class TxDecoderException(Exception):
    pass


class UnexpectedProblemDecoding(TxDecoderException):
    pass


class CannotDecode(TxDecoderException):
    pass


class ParameterDecoded(TypedDict):
    name: str
    type: str
    value: Any


class DataDecoded(TypedDict):
    method: str
    parameters: List[ParameterDecoded]


class MultisendDecoded(TypedDict):
    operation: int
    to: ChecksumAddress
    value: str
    data: Optional[HexStr]
    data_decoded: Optional[DataDecoded]


@cache
def get_db_tx_decoder() -> "DbTxDecoder":
    """
    :return: Tx decoder with every ABI in the database loaded and indexed by function opcode
    .. note::
        Be careful when calling this function in a concurrent way, as if cache is not generated it will compute
        the ``DbTxDecoder`` multiple times, and depending on the number of Contracts in the database it could
        take a lot.
    """

    def _get_db_tx_decoder() -> "DbTxDecoder":
        return DbTxDecoder()

    if running_on_gevent():
        # It's a very intensive CPU task, so to prevent blocking
        # http://www.gevent.org/api/gevent.threadpool.html
        pool = gevent.get_hub().threadpool
        return pool.spawn(_get_db_tx_decoder).get()
    return _get_db_tx_decoder()


def is_db_tx_decoder_loaded() -> bool:
    return get_db_tx_decoder.cache_info().currsize != 0


@cache
def get_tx_decoder() -> "TxDecoder":
    return TxDecoder()


@cache
def get_safe_tx_decoder() -> "SafeTxDecoder":
    return SafeTxDecoder()


class SafeTxDecoder:
    """
    Decode simple txs for Safe contracts. No multisend or nested transactions are decoded
    """

    EXEC_TRANSACTION_SELECTOR = HexBytes("0x6a761202")

    dummy_w3 = Web3()

    def __init__(self):
        logger.info("%s: Loading contract ABIs for decoding", self.__class__.__name__)
        self.fn_selectors_with_abis: Dict[
            bytes, ABIFunction
        ] = self._generate_selectors_with_abis_from_abis(self.get_supported_abis())
        logger.info(
            "%s: Contract ABIs for decoding were loaded", self.__class__.__name__
        )

    def get_abi_function(
        self, data: bytes, address: Optional[ChecksumAddress] = None
    ) -> Optional[ABIFunction]:
        """
        :param data: transaction data
        :param address: contract address in case of ABI colliding
        :return: Abi function for data if it can be decoded, `None` if not found
        """
        try:
            return self.fn_selectors_with_abis[data[:4]]
        except KeyError:
            return None

    def _decode_data(
        self, data: Union[bytes, str], address: Optional[ChecksumAddress] = None
    ) -> Tuple[str, List[Tuple[str, str, Any]]]:
        """
        Decode tx data

        :param data: Tx data as `hex string` or `bytes`
        :param address: contract address in case of ABI colliding
        :return: Tuple with the `function name` and a List of sorted tuples with
            the `name` of the argument, `type` and `value`
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """

        if not data:
            raise CannotDecode(data)

        data = HexBytes(data)
        params = data[4:]
        fn_abi = self.get_abi_function(data, address)
        if not fn_abi:
            raise CannotDecode(data.hex())
        try:
            names = get_abi_input_names(fn_abi)
            types = get_abi_input_types(fn_abi)
            decoded = decode_abi(types, cast(HexBytes, params))
            normalized = map_abi_data(BASE_RETURN_NORMALIZERS, types, decoded)
            values = map(self._parse_decoded_arguments, normalized)
        except (ValueError, DecodingError) as exc:
            logger.warning("Cannot decode %s", data.hex())
            raise UnexpectedProblemDecoding(data) from exc

        return fn_abi["name"], list(zip(names, types, values))

    def _generate_selectors_with_abis_from_abi(
        self, abi: ABIFunction
    ) -> Dict[bytes, ABIFunction]:
        """
        :param abi: ABI
        :return: Dictionary with function selector as bytes and the ContractFunction
        """
        return {
            function_abi_to_4byte_selector(fn_abi): fn_abi
            for fn_abi in abi
            if fn_abi["type"] == "function"
        }

    def _generate_selectors_with_abis_from_abis(
        self, abis: Sequence[ABIFunction]
    ) -> Dict[bytes, ABIFunction]:
        """
        :param abis: Contract ABIs. Last ABIs on the Sequence have preference if there's a collision on the
        selector
        :return: Dictionary with function selector as bytes and the function abi
        """
        return {
            fn_selector: fn_abi
            for supported_abi in abis
            for fn_selector, fn_abi in self._generate_selectors_with_abis_from_abi(
                supported_abi
            ).items()
        }

    def _parse_decoded_arguments(self, value_decoded: Any) -> Any:
        """
        Parse decoded arguments, like converting `bytes` to hexadecimal `str` or `int` and `float` to `str` (to
        prevent problems when deserializing in another languages like JavaScript

        :param value_decoded:
        :return: Dict[str, Any]
        """
        if isinstance(value_decoded, bytes):
            value_decoded = HexBytes(value_decoded).hex()
        return value_decoded

    def add_abi(self, abi: ABIFunction) -> bool:
        """
        Add a new abi without rebuilding the entire decoder

        :return: True if decoder updated, False otherwise
        """
        updated = False
        for selector, new_abi in self._generate_selectors_with_abis_from_abi(
            abi
        ).items():
            if selector not in self.fn_selectors_with_abis:
                self.fn_selectors_with_abis[selector] = new_abi
                updated = True
        return updated

    def decode_parameters_data(
        self, data: bytes, parameters: Sequence[Dict[str, Any]]
    ) -> Sequence[Dict[str, Any]]:
        """
        Decode inner data for function parameters, e.g. Multisend `data` or `data` in Gnosis Safe `execTransaction`

        :param data:
        :param parameters:
        :return: Parameters with extra data
        """
        return parameters

    def decode_transaction_with_types(
        self, data: Union[bytes, str], address: Optional[ChecksumAddress] = None
    ) -> Tuple[str, List[ParameterDecoded]]:
        """
        Decode tx data and return a list of dictionaries

        :param data: Tx data as `hex string` or `bytes`
        :param address: contract address in case of ABI colliding
        :return: Tuple with the `function name` and a list of dictionaries
            [{'name': str, 'type': str, 'value': `depending on type`}...]
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        data = HexBytes(data)
        fn_name, raw_parameters = self._decode_data(data, address=address)
        # Parameters are returned as tuple, convert it to a dictionary
        parameters = [
            {"name": name, "type": argument_type, "value": value}
            for name, argument_type, value in raw_parameters
        ]
        nested_parameters = self.decode_parameters_data(data, parameters)
        return fn_name, nested_parameters

    def decode_transaction(
        self, data: Union[bytes, str], address: Optional[ChecksumAddress] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Decode tx data and return all the parameters in the same dictionary

        :param data: Tx data as `hex string` or `bytes`
        :param address: contract address in case of ABI colliding
        :return: Tuple with the `function name` and a dictionary with the arguments of the function
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        fn_name, decoded_transactions_with_types = self.decode_transaction_with_types(
            data, address=address
        )
        decoded_transactions = {
            d["name"]: d["value"] for d in decoded_transactions_with_types
        }
        return fn_name, decoded_transactions

    def get_supported_abis(self) -> Iterable[ABIFunction]:
        safe_abis = [
            get_safe_V0_0_1_contract(self.dummy_w3).abi,
            get_safe_V1_0_0_contract(self.dummy_w3).abi,
            get_safe_V1_1_1_contract(self.dummy_w3).abi,
            get_safe_V1_3_0_contract(self.dummy_w3).abi,
            get_safe_V1_4_1_contract(self.dummy_w3).abi,
        ]

        # Order is important. If signature is the same (e.g. renaming of `baseGas`) last elements in the list
        # will take preference
        return safe_abis

    def get_data_decoded(
        self, data: Union[str, bytes], address: Optional[ChecksumAddress] = None
    ) -> Optional[DataDecoded]:
        """
        Return data prepared for serializing

        :param data:
        :param address: contract address in case of ABI colliding
        :return:
        """
        if not data:
            return None
        try:
            fn_name, parameters = self.decode_transaction_with_types(
                data, address=address
            )
            return {"method": fn_name, "parameters": parameters}
        except TxDecoderException:
            return None


class TxDecoder(SafeTxDecoder):
    """
    Decode MultiSend and use some hardcoded ABIs (Gnosis contracts, erc20/721 tokens...)
    """

    @cached_property
    def multisend_abis(self) -> List[ABIFunction]:
        return [get_multi_send_contract(self.dummy_w3).abi]

    @cached_property
    def multisend_fn_selectors_with_abis(self) -> Dict[bytes, ABIFunction]:
        return self._generate_selectors_with_abis_from_abis(self.multisend_abis)

    def decode_multisend_data(self, data: Union[bytes, str]) -> List[MultisendDecoded]:
        """
        Decodes Multisend raw data to Multisend dictionary

        :param data:
        :return:
        """
        try:
            multisend_txs = MultiSend.from_transaction_data(data)
            return [
                {
                    "operation": multisend_tx.operation.value,
                    "to": multisend_tx.to,
                    "value": str(multisend_tx.value),
                    "data": multisend_tx.data.hex() if multisend_tx.data else None,
                    "data_decoded": self.get_data_decoded(
                        multisend_tx.data, address=multisend_tx.to
                    ),
                }
                for multisend_tx in multisend_txs
            ]
        except ValueError:
            logger.warning(
                "Problem decoding multisend transaction with data=%s",
                HexBytes(data).hex(),
                exc_info=True,
            )

    def _parse_decoded_arguments(self, value_decoded: Any) -> Any:
        """
        Add custom parsing to the decoded function arguments. Convert numbers to strings and
        recursively parse lists, tuples and sets.

        :param value_decoded:
        :return:
        """
        value_decoded = super()._parse_decoded_arguments(value_decoded)
        if isinstance(value_decoded, (int, float)):
            value_decoded = str(
                value_decoded
            )  # Return numbers as `str` for json compatibility
        elif isinstance(value_decoded, (list, tuple, set)):
            value_decoded = [
                self._parse_decoded_arguments(e) for e in value_decoded
            ]  # Recursive parsing inside sequences
        return value_decoded

    def get_supported_abis(self) -> Iterable[ABIFunction]:
        supported_abis = super().get_supported_abis()

        aave_contracts = [
            aave_a_token,
            aave_lending_pool,
            aave_lending_pool_addresses_provider,
            aave_lending_pool_core,
        ]
        initializable_admin_upgradeability_proxy_contracts = [
            initializable_admin_upgradeability_proxy_abi
        ]
        balancer_contracts = [balancer_bactions, balancer_exchange_proxy]
        chainlink_contracts = [chainlink_token_abi]
        compound_contracts = [ctoken_abi, comptroller_abi]
        idle_contracts = [idle_token_v3]
        maker_dao_contracts = maker_dao_abis
        open_zeppelin_contracts = [
            open_zeppelin_admin_upgradeability_proxy,
            open_zeppelin_proxy_admin,
        ]
        request_contracts = [
            request_erc20_proxy,
            request_erc20_swap_to_pay,
            request_ethereum_proxy,
        ]
        sablier_contracts = [sablier_ctoken_manager, sablier_payroll, sablier_abi]

        snapshot_contracts = [snapshot_delegate_registry_abi]

        exchanges = [
            get_uniswap_exchange_contract(self.dummy_w3).abi,
            get_kyber_network_proxy_contract(self.dummy_w3).abi,
        ]

        sight_contracts = [
            conditional_token_abi,
            market_maker_abi,
            market_maker_factory_abi,
        ]
        gnosis_protocol = [
            gnosis_protocol_abi,
            fleet_factory_deterministic_abi,
            fleet_factory_abi,
        ]

        gnosis_safe = [gnosis_safe_allowance_module_abi]
        erc_contracts = [
            get_erc721_contract(self.dummy_w3).abi,
            get_erc20_contract(self.dummy_w3).abi,
        ]

        timelock_contracts = [timelock_abi]

        # Order is important. If signature is the same (e.g. renaming of `baseGas`) last elements in the list
        # will take preference
        return (
            timelock_contracts
            + initializable_admin_upgradeability_proxy_contracts
            + aave_contracts
            + balancer_contracts
            + chainlink_contracts
            + idle_contracts
            + maker_dao_contracts
            + request_contracts
            + sablier_contracts
            + snapshot_contracts
            + open_zeppelin_contracts
            + compound_contracts
            + exchanges
            + sight_contracts
            + gnosis_protocol
            + gnosis_safe
            + erc_contracts
            + self.multisend_abis
            + supported_abis
        )

    def decode_parameters_data(
        self, data: bytes, parameters: Sequence[Dict[str, Any]]
    ) -> Sequence[Dict[str, Any]]:
        """
        Decode inner data for function parameters, in this case Multisend `data` and
        `data` in Gnosis Safe `execTransaction`

        :param data:
        :param parameters:
        :return: Parameters with an extra object with key `value_decoded` if decoding is possible
        """
        fn_selector = data[:4]
        if fn_selector in self.multisend_fn_selectors_with_abis:
            # If multisend, decode the transactions
            parameters[0]["value_decoded"] = self.decode_multisend_data(data)

        elif (
            fn_selector == self.EXEC_TRANSACTION_SELECTOR
            and len(parameters) > 2
            and (data := HexBytes(parameters[2]["value"]))
        ):
            # If Gnosis Safe `execTransaction` decode the inner transaction
            # function execTransaction(address to, uint256 value, bytes calldata data...)
            # selector is `0x6a761202` and parameters[2] is data
            try:
                parameters[2]["value_decoded"] = self.get_data_decoded(
                    data, address=parameters[0]["value"]
                )
            except TxDecoderException:
                logger.warning("Cannot decode `execTransaction`", exc_info=True)
        return parameters


class DbTxDecoder(TxDecoder):
    """
    Decode contracts from ABIs in database
    """

    cache_abis_by_address = TTLCache(maxsize=2048, ttl=60 * 5)  # 5 minutes of caching

    @cachedmethod(cache=operator.attrgetter("cache_abis_by_address"))
    def get_contract_abi(
        self, address: ChecksumAddress
    ) -> Optional[Dict[bytes, ABIFunction]]:
        """
        :param address: Contract address
        :return: Dictionary of function selects with ABIFunction if found, `None` otherwise
        """
        abis = (
            ContractAbi.objects.filter(contracts__address=address)
            .order_by("relevance")
            .values_list("abi", flat=True)
        )
        if abis:
            return self._generate_selectors_with_abis_from_abi(abis[0])

    def get_abi_function(
        self, data: bytes, address: Optional[ChecksumAddress] = None
    ) -> Optional[ABIFunction]:
        """
        :param data: transaction data
        :param address: contract address in case of ABI colliding
        :return: Abi function for data if it can be decoded, `None` if not found
        """
        selector = data[:4]
        # Check first that selector is supported on our database
        if selector in self.fn_selectors_with_abis:
            # Try to use specific ABI if address provided
            if address:
                contract_selectors_with_abis = self.get_contract_abi(address)
                if (
                    contract_selectors_with_abis
                    and selector in contract_selectors_with_abis
                ):
                    # If the selector is available in the abi specific for the address we will use that one
                    # Otherwise we fall back to the general abi that matches the selector
                    return contract_selectors_with_abis[selector]
            return self.fn_selectors_with_abis[selector]

    def get_supported_abis(self) -> Iterable[Type[Contract]]:
        supported_abis = super().get_supported_abis()
        db_abis = (
            ContractAbi.objects.all()
            .order_by("-relevance")
            .values_list("abi", flat=True)
            .iterator()
        )
        return itertools.chain(db_abis, supported_abis)
