from logging import getLogger
from typing import Any, Dict, List, Tuple, Union

from eth_utils import function_abi_to_4byte_selector
from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract

from gnosis.eth.contracts import (get_safe_contract, get_safe_V0_0_1_contract,
                                  get_safe_V1_0_0_contract)

logger = getLogger(__name__)


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
        self.supported_contracts = [get_safe_contract(Web3()),
                                    get_safe_V1_0_0_contract(Web3()),
                                    get_safe_V0_0_1_contract(Web3())]

        # Web3 generates possible selectors every time. We cache that and use a dict to do a fast check
        self.supported_fn_selectors: Dict[bytes, None] = {}
        for supported_contract in self.supported_contracts:
            for selector in self._generate_selectors_from_contract(supported_contract):
                self.supported_fn_selectors[selector] = None

    def _generate_selectors_from_contract(self, contract: Contract) -> List[bytes]:
        return [function_abi_to_4byte_selector(contract_fn.abi) for contract_fn in contract.all_functions()]

    def _parse_decoded_arguments(self, decoded: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse decoded arguments, like converting `bytes` to hexadecimal `str`
        :param decoded:
        :return: Dict[str, Any]
        """
        parsed = {}
        for k, v in decoded.items():
            if isinstance(v, bytes):
                value = HexBytes(v).hex()
            else:
                value = v
            parsed[k] = value
        return parsed

    def decode_transaction(self, data: Union[bytes, str]) -> Tuple[str, Dict[str, Any]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a dictionary with the arguments of the function
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        if not data:
            raise CannotDecode(data)

        data = HexBytes(data)
        selector = data[:4]
        if selector not in self.supported_fn_selectors:
            raise CannotDecode(data.hex())

        for contract in self.supported_contracts:
            try:
                contract_function, arguments = contract.decode_function_input(data)
                function_name = contract_function.fn_name
                return function_name, self._parse_decoded_arguments(arguments)
            except ValueError as exc:  # ValueError: Could not find any function with matching selector
                if not exc.args or exc.args[0] != 'Could not find any function with matching selector':
                    raise UnexpectedProblemDecoding from exc
        raise CannotDecode(data.hex())
