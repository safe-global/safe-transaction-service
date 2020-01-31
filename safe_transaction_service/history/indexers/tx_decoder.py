from logging import getLogger
from typing import Any, Dict, List, Tuple, Union, cast

from eth_utils import function_abi_to_4byte_selector
from hexbytes import HexBytes
from web3 import Web3
from web3._utils.abi import (get_abi_input_names, get_abi_input_types,
                             map_abi_data)
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.contract import Contract, ContractFunction

from gnosis.eth.contracts import (get_safe_contract, get_safe_V0_0_1_contract,
                                  get_safe_V1_0_0_contract)

logger = getLogger(__name__)


AbiType = Dict[str, Any]


class TxDecoderException(Exception):
    pass


class UnexpectedProblemDecoding(TxDecoderException):
    pass


class CannotDecode(TxDecoderException):
    pass


def get_tx_decoder() -> 'TxDecoder':
    if not hasattr(get_tx_decoder, 'instance'):
        get_tx_decoder.instance = TxDecoder()
    return get_tx_decoder.instance


class TxDecoder:
    """
    Decode txs for supported contracts
    """
    def __init__(self):
        self.dummy_w3 = Web3()
        # Order is important. If signature is the same (e.g. renaming of `baseGas`) last elements in the list
        # will take preference
        self.supported_contracts = [get_safe_V0_0_1_contract(self.dummy_w3),
                                    get_safe_V1_0_0_contract(self.dummy_w3),
                                    get_safe_contract(self.dummy_w3)]

        # Web3 generates possible selectors every time. We cache that and use a dict to do a fast check
        # Store selectors with abi
        self.supported_fn_selectors: Dict[bytes, ContractFunction] = {}
        for supported_contract in self.supported_contracts:
            self.supported_fn_selectors.update(self._generate_selectors_with_abis_from_contract(supported_contract))

    def _generate_selectors_with_abis_from_contract(self, contract: Contract) -> Dict[bytes, ContractFunction]:
        return {function_abi_to_4byte_selector(contract_fn.abi): contract_fn
                for contract_fn in contract.all_functions()}

    def _parse_decoded_arguments(self, decoded_value: Any) -> Any:
        """
        Parse decoded arguments, like converting `bytes` to hexadecimal `str`
        :param decoded:
        :return: Dict[str, Any]
        """
        if isinstance(decoded_value, bytes):
            decoded_value = HexBytes(decoded_value).hex()
        return decoded_value

    def decode_transaction_with_types(self, data: Union[bytes, str]) -> Tuple[str, List[Tuple[str, str, Any]]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a list of dictionaries dictionary {'name', 'type', 'value'}
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
        fn_name, parameters = self._decode_transaction(data)
        return fn_name, {name: value for name, argument_type, value in parameters}

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
        except ValueError as exc:
            raise UnexpectedProblemDecoding from exc

        return contract_fn.fn_name, list(zip(names, types, values))
