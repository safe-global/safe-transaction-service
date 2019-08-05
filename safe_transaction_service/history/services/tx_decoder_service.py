from logging import getLogger
from gnosis.eth.contracts import get_safe_contract
from typing import Any, Dict, List, Set, Union, Tuple, Optional

from gnosis.eth import EthereumClient
from hexbytes import HexBytes
from web3 import Web3

from ..models import InternalTx, InternalTxDecoded
from .transaction_indexer import TransactionIndexer

logger = getLogger(__name__)


class TxDecoderServiceException(Exception):
    pass


class UnexpectedProblemDecoding(TxDecoderServiceException):
    pass


class CannotDecode(TxDecoderServiceException):
    pass


class TxDecoderServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = TxDecoderService()
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TxDecoderService:
    def __init__(self):
        self.supported_contracts = [get_safe_contract(Web3())]

    def process_transaction_from_internal_tx(self, internal_tx: InternalTx) -> Optional[InternalTxDecoded]:
        try:
            function_name, arguments = self.decode_transaction(internal_tx.data)
            internal_tx_decoded, _ = InternalTxDecoded.objects.get_or_create(internal_tx=internal_tx,
                                                                             defaults={
                                                                                 'function_name': function_name,
                                                                                 'arguments': arguments}
                                                                             )
            return internal_tx_decoded
        except CannotDecode:
            pass
        return None

    def decode_transaction(self, data: Union[bytes, str]) -> Tuple[str, Dict[str, Any]]:
        try:
            for contract in self.supported_contracts:
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
        for k, v in decoded:
            if isinstance(v, bytes):
                value = HexBytes(v).hex()
            else:
                value = v
            parsed[k] = value
        return parsed
