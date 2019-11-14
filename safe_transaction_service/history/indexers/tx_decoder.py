from logging import getLogger
from typing import Any, Dict, Tuple, Union

from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.contracts import get_safe_V1_0_0_contract, get_safe_V0_0_1_contract, get_safe_contract

logger = getLogger(__name__)


class TxDecoderException(Exception):
    pass


class UnexpectedProblemDecoding(TxDecoderException):
    pass


class CannotDecode(TxDecoderException):
    pass


class TxDecoder:
    """
    Decode txs for supported contracts
    """
    def __init__(self):
        self.supported_contracts = [get_safe_contract(Web3()),
                                    get_safe_V1_0_0_contract(Web3()),
                                    get_safe_V0_0_1_contract(Web3())]

    def decode_transaction(self, data: Union[bytes, str]) -> Tuple[str, Dict[str, Any]]:
        """
        Decode tx data
        :param data: Tx data as `hex string` or `bytes`
        :return: Tuple with the `function name` and a dictionary with the arguments of the function
        :raises: CannotDecode if data cannot be decoded. You should catch this exception when using this function
        :raises: UnexpectedProblemDecoding if there's an unexpected problem decoding (it shouldn't happen)
        """
        for contract in self.supported_contracts:
            try:
                contract_function, arguments = contract.decode_function_input(data)
                function_name = contract_function.fn_name
                return function_name, self.__parse_decoded_arguments(arguments)
            except ValueError as exc:  # ValueError: Could not find any function with matching selector
                if not exc.args or exc.args[0] != 'Could not find any function with matching selector':
                    raise UnexpectedProblemDecoding from exc
        raise CannotDecode(HexBytes(data).hex())

    def __parse_decoded_arguments(self, decoded: Dict[str, Any]) -> Dict[str, Any]:
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
