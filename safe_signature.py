from abc import ABC, abstractmethod
from enum import Enum
from logging import getLogger
from typing import List, Union

from eth_abi import encode_single
from eth_abi.exceptions import DecodingError
from eth_account.messages import defunct_hash_message
from ethereum.utils import checksum_encode
from hexbytes import HexBytes
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClient
from gnosis.eth.contracts import get_safe_contract, get_safe_V1_1_1_contract
from gnosis.safe.signatures import (get_signing_address, signature_split,
                                    signature_to_bytes)

logger = getLogger(__name__)


EthereumBytes = Union[bytes, str]


class SafeSignatureException(Exception):
    pass


class CannotCheckEIP1271ContractSignature(SafeSignatureException):
    pass


class SafeSignatureType(Enum):
    CONTRACT_SIGNATURE = 0
    APPROVED_HASH = 1
    EOA = 2
    ETH_SIGN = 3

    @staticmethod
    def from_v(v: int):
        if v == 0:
            return SafeSignatureType.CONTRACT_SIGNATURE
        elif v == 1:
            return SafeSignatureType.APPROVED_HASH
        elif v > 30:
            return SafeSignatureType.ETH_SIGN
        else:
            return SafeSignatureType.EOA


class SafeSignature(ABC):
    def __init__(self, signature: EthereumBytes, safe_tx_hash: EthereumBytes):
        self.signature = HexBytes(signature)
        self.safe_tx_hash = HexBytes(safe_tx_hash)
        self.v, self.r, self.s = signature_split(self.signature)

    def __str__(self):
        return f'SafeSignature type={self.signature_type.name} owner={self.owner}'

    @classmethod
    def parse_signature(cls, signatures: EthereumBytes, safe_tx_hash: EthereumBytes,
                        ignore_trailing: bool = True) -> List['SafeSignature']:
        """
        :param signatures: One or more signatures appended. EIP1271 data at the end is supported.
        :param safe_tx_hash:
        :param ignore_trailing: Ignore trailing data on the signature. Some libraries pad it and add some zeroes at
            the end
        :return: List of SafeSignatures decoded
        """
        if not signatures:
            return []
        elif isinstance(signatures, str):
            signatures = HexBytes(signatures)

        signature_size = 65  # For contract signatures there'll be some data at the end
        data_position = len(signatures)  # For contract signatures, to stop parsing at data position

        safe_signatures = []
        for i in range(0, len(signatures), signature_size):
            if i >= data_position:  # If contract signature data position is reached, stop
                break

            signature = signatures[i: i + signature_size]
            if ignore_trailing and len(signature) < 65:
                # Trailing stuff
                break
            v, r, s = signature_split(signature)
            signature_type = SafeSignatureType.from_v(v)
            safe_signature: 'SafeSignature'
            if signature_type == SafeSignatureType.CONTRACT_SIGNATURE:
                if s < data_position:
                    data_position = s
                contract_signature_len = int.from_bytes(signatures[s:s + 32], 'big')  # Len size is 32 bytes
                contract_signature = signatures[s + 32: s + 32 + contract_signature_len]  # Skip array size (32 bytes)
                safe_signature = SafeSignatureContract(signature, safe_tx_hash, contract_signature)
            elif signature_type == SafeSignatureType.APPROVED_HASH:
                safe_signature = SafeSignatureApprovedHash(signature, safe_tx_hash)
            elif signature_type == SafeSignatureType.EOA:
                safe_signature = SafeSignatureEOA(signature, safe_tx_hash)
            elif signature_type == SafeSignatureType.ETH_SIGN:
                safe_signature = SafeSignatureEthSign(signature, safe_tx_hash)

            safe_signatures.append(safe_signature)
        return safe_signatures

    def export_signature(self) -> HexBytes:
        """
        Exports signature in a format that's valid individually. That's important for contract signatures, as it
        will fix the offset
        :return:
        """
        return self.signature

    @property
    @abstractmethod
    def owner(self):
        """
        :return: Decode owner from signature, without any further validation (signature can be not valid)
        """
        raise NotImplementedError

    @abstractmethod
    def is_valid(self, ethereum_client: EthereumClient, safe_address: str) -> bool:
        """
        :param ethereum_client: Required for Contract Signature and Approved Hash check
        :param safe_address: Required for Approved Hash check
        :return: `True` if signature is valid, `False` otherwise
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def signature_type(self) -> SafeSignatureType:
        raise NotImplementedError


class SafeSignatureContract(SafeSignature):
    EIP1271_MAGIC_VALUE = HexBytes(0x20c13b0b)
    EIP1271_MAGIC_VALUE_UPDATED = HexBytes(0x1626ba7e)

    def __init__(self, signature: EthereumBytes, safe_tx_hash: EthereumBytes, contract_signature: EthereumBytes):
        super().__init__(signature, safe_tx_hash)
        self.contract_signature = HexBytes(contract_signature)

    @property
    def owner(self):
        """
        :return: Address of contract signing. No further checks to get the owner are needed,
            but it could be a non existing contract
        """
        contract_address = checksum_encode(self.r)
        return contract_address

    @property
    def signature_type(self):
        return SafeSignatureType.CONTRACT_SIGNATURE

    def export_signature(self) -> HexBytes:
        """
        Fix offset (s) and append `contract_signature` at the end of the signature
        :return:
        """
        return HexBytes(signature_to_bytes(self.v, self.r, 65) + encode_single('bytes', self.contract_signature))

    def is_valid(self, ethereum_client: EthereumClient, *args) -> bool:
        safe_contract = get_safe_V1_1_1_contract(ethereum_client.w3, self.owner)
        # Newest versions of the Safe contract have `isValidSignature` on the compatibility fallback handler
        for block_identifier in ('pending', 'latest'):
            try:
                return safe_contract.functions.isValidSignature(
                    self.safe_tx_hash,
                    self.contract_signature
                ).call(block_identifier=block_identifier) in (self.EIP1271_MAGIC_VALUE,
                                                              self.EIP1271_MAGIC_VALUE_UPDATED)
            except (ValueError, BadFunctionCallOutput, DecodingError):
                # Error using `pending` block identifier or contract does not exist
                logger.warning('Cannot check EIP1271 signature from contract %s', self.owner)
        return False


class SafeSignatureApprovedHash(SafeSignature):
    @property
    def owner(self):
        return checksum_encode(self.r)

    @property
    def signature_type(self):
        return SafeSignatureType.APPROVED_HASH

    @classmethod
    def build_for_owner(cls, owner: str, safe_tx_hash: str) -> 'SafeSignatureApprovedHash':
        r = owner.lower().replace('0x', '').rjust(64, '0')
        s = '0' * 64
        v = '01'
        return cls(HexBytes(r + s + v), safe_tx_hash)

    def is_valid(self, ethereum_client: EthereumClient, safe_address: str) -> bool:
        safe_contract = get_safe_contract(ethereum_client.w3, safe_address)
        exception: Exception
        for block_identifier in ('pending', 'latest'):
            try:
                return safe_contract.functions.approvedHashes(
                    self.owner,
                    self.safe_tx_hash
                ).call(block_identifier=block_identifier) == 1
            except BadFunctionCallOutput as e:  # Error using `pending` block identifier
                exception = e
        raise exception  # This should never happen


class SafeSignatureEthSign(SafeSignature):
    @property
    def ronin_owner(self):
        # defunct_hash_message prepends `\x19Ethereum Signed Message:\n32`
        message_hash = defunct_hash_message(text=self.safe_tx_hash.hex())
        return get_signing_address(message_hash, self.v - 4, self.r, self.s)

    @property
    def owner(self):
        # defunct_hash_message prepends `\x19Ethereum Signed Message:\n32`
        message_hash = defunct_hash_message(primitive=self.safe_tx_hash)
        return get_signing_address(message_hash, self.v - 4, self.r, self.s)

    @property
    def signature_type(self):
        return SafeSignatureType.ETH_SIGN

    def is_valid(self, *args) -> bool:
        return True


class SafeSignatureEOA(SafeSignature):
    @property
    def owner(self):
        return get_signing_address(self.safe_tx_hash, self.v, self.r, self.s)

    @property
    def signature_type(self):
        return SafeSignatureType.EOA

    def is_valid(self, *args) -> bool:
        return True
