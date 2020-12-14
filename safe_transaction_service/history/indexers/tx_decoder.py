from functools import cached_property
from logging import getLogger
from typing import Any, Dict, List, Sequence, Tuple, Type, Union, cast

from cachetools import TTLCache, cached
from eth_abi.exceptions import InsufficientDataBytes
from eth_utils import function_abi_to_4byte_selector
from hexbytes import HexBytes
from web3 import Web3
from web3._utils.abi import (get_abi_input_names, get_abi_input_types,
                             map_abi_data)
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.contract import Contract, ContractFunction

from gnosis.eth.contracts import (get_erc20_contract, get_erc721_contract,
                                  get_kyber_network_proxy_contract,
                                  get_multi_send_contract, get_safe_contract,
                                  get_safe_V0_0_1_contract,
                                  get_safe_V1_0_0_contract,
                                  get_uniswap_exchange_contract)
from gnosis.safe.multi_send import MultiSend

from safe_transaction_service.contracts.models import ContractAbi

from .decoder_abis.aave import (aave_a_token, aave_lending_pool,
                                aave_lending_pool_addresses_provider,
                                aave_lending_pool_core)
from .decoder_abis.admin_upgradeability_proxy import \
    initializable_admin_upgradeability_proxy_abi
from .decoder_abis.balancer import balancer_bactions, balancer_exchange_proxy
from .decoder_abis.chainlink import chainlink_token_abi
from .decoder_abis.compound import comptroller_abi, ctoken_abi
from .decoder_abis.gnosis_protocol import (fleet_factory_abi,
                                           fleet_factory_deterministic_abi,
                                           gnosis_protocol_abi)
from .decoder_abis.gnosis_safe import allowance_module_abi, decoging_test_abi
from .decoder_abis.idle import idle_token_v3
from .decoder_abis.maker_dao import maker_dao_abis
from .decoder_abis.open_zeppelin import (
    open_zeppelin_admin_upgradeability_proxy, open_zeppelin_proxy_admin)
from .decoder_abis.request import (request_erc20_proxy,
                                   request_erc20_swap_to_pay,
                                   request_ethereum_proxy)
from .decoder_abis.sablier import (sablier_abi, sablier_ctoken_manager,
                                   sablier_payroll)
from .decoder_abis.sight import (conditional_token_abi, market_maker_abi,
                                 market_maker_factory_abi)
from .decoder_abis.snapshot import snapshot_delegate_registry_abi
from .decoder_abis.timelock import timelock_abi

logger = getLogger(__name__)


AbiType = Dict[str, Any]


class TxDecoderException(Exception):
    pass


class UnexpectedProblemDecoding(TxDecoderException):
    pass


class CannotDecode(TxDecoderException):
    pass


@cached(TTLCache(maxsize=2, ttl=60 * 60))  # Cached 1 hour
def get_db_tx_decoder() -> 'TxDecoder':
    return DbTxDecoder()


def get_tx_decoder() -> 'TxDecoder':
    if not hasattr(get_tx_decoder, 'instance'):
        get_tx_decoder.instance = TxDecoder()
    return get_tx_decoder.instance


def get_safe_tx_decoder() -> 'SafeTxDecoder':
    if not hasattr(get_safe_tx_decoder, 'instance'):
        get_safe_tx_decoder.instance = SafeTxDecoder()
    return get_safe_tx_decoder.instance


class SafeTxDecoder:
    dummy_w3 = Web3()
    """
    Decode txs for supported contracts
    """
    def __init__(self):
        logger.info('Loading contract ABIs for decoding')
        self.supported_contracts: List[Type[Contract]] = self.get_supported_contracts()
        logger.info('Contract ABIs for decoding were loaded')

    def get_supported_contracts(self) -> List[Type[Contract]]:
        safe_contracts = [get_safe_V0_0_1_contract(self.dummy_w3), get_safe_V1_0_0_contract(self.dummy_w3),
                          get_safe_contract(self.dummy_w3)]

        # Order is important. If signature is the same (e.g. renaming of `baseGas`) last elements in the list
        # will take preference
        return safe_contracts

    def _generate_selectors_with_abis_from_contract(self, contract: Contract) -> Dict[bytes, ContractFunction]:
        """
        :param contract: Web3 Contract
        :return: Dictionary with function selector as bytes and the ContractFunction
        """
        return {function_abi_to_4byte_selector(contract_fn.abi): contract_fn
                for contract_fn in contract.all_functions()}

    def _generate_selectors_with_abis_from_contracts(self, contracts: Sequence[Contract]) -> Dict[bytes,
                                                                                                  ContractFunction]:
        """
        :param contracts: Web3 Contracts. Last contracts on the Iterable have preference if there's a collision on the
        selector
        :return: Dictionary with function selector as bytes and the ContractFunction.
        """
        # TODO Use comprehension
        supported_fn_selectors: Dict[bytes, ContractFunction] = {}
        for supported_contract in contracts:
            supported_fn_selectors.update(self._generate_selectors_with_abis_from_contract(supported_contract))
        return supported_fn_selectors

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

    @cached_property
    def supported_fn_selectors(self) -> Dict[bytes, ContractFunction]:
        """
        Web3 generates possible selectors every time. We cache that and use a dict to do a fast check
        Store function selectors with abi
        :return: A dictionary with the selectors and the contract function
        """
        return self._generate_selectors_with_abis_from_contracts(self.supported_contracts)

    def get_data_decoded(self, data: Union[str, bytes]):
        """
        Return data prepared for serializing
        :param data:
        :return:
        """
        try:
            data = HexBytes(data)
            fn_name, parameters = self.decode_transaction_with_types(data)
            return {'method': fn_name,
                    'parameters': parameters}
        except TxDecoderException:
            return None

    def decode_transaction_with_types(self, data: Union[bytes, str]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a list of dictionaries
        [{'name': str, 'type': str, 'value': `depending on type`}...]
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        fn_name, parameters = self._decode_transaction(data)
        return fn_name, [{'name': name, 'type': argument_type, 'value': value}
                         for name, argument_type, value in parameters]

    def decode_transaction(self, data: Union[bytes, str]) -> Tuple[str, Dict[str, Any]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a dictionary with the arguments of the function
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        fn_name, decoded_transactions_with_types = self.decode_transaction_with_types(data)
        decoded_transactions = {d['name']: d['value'] for d in decoded_transactions_with_types}
        return fn_name, decoded_transactions

    def _decode_transaction(self, data: Union[bytes, str]) -> Tuple[str, List[Tuple[str, str, Any]]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a List of sorted tuples with
        the `name` of the argument, `type` and `value`
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """

        if not data:
            raise CannotDecode(data)

        data = HexBytes(data)
        selector, params = data[:4], data[4:]
        if selector not in self.supported_fn_selectors:
            raise CannotDecode(data.hex())

        try:
            contract_fn = self.supported_fn_selectors[selector]
            names = get_abi_input_names(contract_fn.abi)
            types = get_abi_input_types(contract_fn.abi)
            decoded = self.dummy_w3.codec.decode_abi(types, cast(HexBytes, params))
            normalized = map_abi_data(BASE_RETURN_NORMALIZERS, types, decoded)
            values = map(self._parse_decoded_arguments, normalized)
        except (ValueError, InsufficientDataBytes) as exc:
            logger.warning('Cannot decode %s', data.hex())
            raise UnexpectedProblemDecoding(data) from exc

        return contract_fn.fn_name, list(zip(names, types, values))


class TxDecoder(SafeTxDecoder):
    def __init__(self):
        self.multisend_contracts: List[Type[Contract]] = [get_multi_send_contract(self.dummy_w3)]
        super().__init__()

    def get_supported_contracts(self) -> List[Type[Contract]]:
        supported_contracts = super().get_supported_contracts()

        aave_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (aave_a_token, aave_lending_pool,
                                                                          aave_lending_pool_addresses_provider,
                                                                          aave_lending_pool_core)]
        initializable_admin_upgradeability_proxy_contracts = [
            self.dummy_w3.eth.contract(abi=initializable_admin_upgradeability_proxy_abi)
        ]
        balancer_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (balancer_bactions,
                                                                              balancer_exchange_proxy)]
        chainlink_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (chainlink_token_abi,)]
        compound_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (ctoken_abi, comptroller_abi)]
        idle_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (idle_token_v3,)]
        maker_dao_contracts = [
            self.dummy_w3.eth.contract(abi=abi)
            for abi in maker_dao_abis
        ]
        open_zeppelin_contracts = [self.dummy_w3.eth.contract(abi=abi)
                                   for abi in (open_zeppelin_admin_upgradeability_proxy, open_zeppelin_proxy_admin)]
        request_contracts = [self.dummy_w3.eth.contract(abi=abi)
                             for abi in (request_erc20_proxy, request_erc20_swap_to_pay, request_ethereum_proxy)]
        sablier_contracts = [self.dummy_w3.eth.contract(abi=abi)
                             for abi in (sablier_ctoken_manager, sablier_payroll, sablier_abi)]

        snapshot_contracts = [self.dummy_w3.eth.contract(abi=abi)
                              for abi in (snapshot_delegate_registry_abi,)]

        exchanges = [get_uniswap_exchange_contract(self.dummy_w3),
                     get_kyber_network_proxy_contract(self.dummy_w3)]

        sight_contracts = [self.dummy_w3.eth.contract(abi=abi) for abi in (conditional_token_abi,
                                                                           market_maker_abi,
                                                                           market_maker_factory_abi)]
        gnosis_protocol = [self.dummy_w3.eth.contract(abi=abi) for abi in (gnosis_protocol_abi,
                                                                           fleet_factory_deterministic_abi,
                                                                           fleet_factory_abi)]

        gnosis_safe = [self.dummy_w3.eth.contract(abi=abi) for abi in (allowance_module_abi,)]
        erc_contracts = [get_erc721_contract(self.dummy_w3),
                         get_erc20_contract(self.dummy_w3)]

        test_contracts = [
            self.dummy_w3.eth.contract(abi=decoging_test_abi)
        ]  # https://rinkeby.etherscan.io/address/0x479adf13cc2e1844451f71dcf0bf5194df53b14b#code

        timelock_contracts = [
            self.dummy_w3.eth.contract(abi=timelock_abi)
        ]

        # Order is important. If signature is the same (e.g. renaming of `baseGas`) last elements in the list
        # will take preference
        return (test_contracts + timelock_contracts
                + initializable_admin_upgradeability_proxy_contracts + aave_contracts
                + balancer_contracts + chainlink_contracts + idle_contracts
                + maker_dao_contracts + request_contracts + sablier_contracts + snapshot_contracts
                + open_zeppelin_contracts
                + compound_contracts + exchanges
                + sight_contracts + gnosis_protocol + gnosis_safe + erc_contracts
                + self.multisend_contracts + supported_contracts)

    def _parse_decoded_arguments(self, value_decoded: Any) -> Any:
        """
        Decode integers also
        :param value_decoded:
        :return:
        """
        # TODO Decode on serializer, but it's tricky as it has a nested decoding
        value_decoded = super()._parse_decoded_arguments(value_decoded)
        if isinstance(value_decoded, (int, float)):
            value_decoded = str(value_decoded)
        elif isinstance(value_decoded, (list, tuple)):
            value_decoded = list([self._parse_decoded_arguments(e) for e in value_decoded])
        return value_decoded

    @cached_property
    def multisend_fn_selectors(self) -> Dict[bytes, ContractFunction]:
        return self._generate_selectors_with_abis_from_contracts(self.multisend_contracts)

    def decode_transaction_with_types(self, data: Union[bytes, str]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Add support for multisend and Gnosis Safe `execTransaction`
        """
        data = HexBytes(data)
        fn_name, parameters = super().decode_transaction_with_types(data)

        # If multisend, decode the transactions
        if data[:4] in self.multisend_fn_selectors:
            parameters[0]['value_decoded'] = self.get_data_decoded_for_multisend(data)

        # If Gnosis Safe `execTransaction` decode the inner transaction
        # function execTransaction(address to, uint256 value, bytes calldata data...)
        # selector is `0x6a761202` and parameters[2] is data
        if data[:4] == HexBytes('0x6a761202') and len(parameters) > 2 and (data := HexBytes(parameters[2]['value'])):
            try:
                parameters[2]['value_decoded'] = self.get_data_decoded(data)
            except TxDecoderException:
                logger.warning('Cannot decode `execTransaction`', exc_info=True)

        return fn_name, parameters

    def get_data_decoded_for_multisend(self, data: Union[bytes, str]) -> List[Dict[str, Any]]:
        """
        Return a multisend
        :param data:
        :return:
        """
        try:
            multisend_txs = MultiSend.from_transaction_data(data)
            return [{'operation': multisend_tx.operation.value,
                     'to': multisend_tx.to,
                     'value': multisend_tx.value,
                     'data': multisend_tx.data.hex(),
                     'data_decoded': self.get_data_decoded(multisend_tx.data),
                     } for multisend_tx in multisend_txs]
        except ValueError:
            logger.warning('Problem decoding multisend transaction with data=%s', HexBytes(data).hex(), exc_info=True)


class DbTxDecoder(TxDecoder):
    """
    Decode contracts from ABIs in database
    """

    def get_supported_contracts(self) -> List[Type[Contract]]:
        supported_contracts = super().get_supported_contracts()
        db_contracts = [self.dummy_w3.eth.contract(abi=abi)
                        for abi in ContractAbi.objects.all().order_by('-relevance').values_list('abi', flat=True)]
        return db_contracts + supported_contracts
