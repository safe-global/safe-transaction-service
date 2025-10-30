import dataclasses

from eth_abi import encode as abi_encode
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.account_abstraction.user_operation import UserOperationMetadata
from safe_eth.eth.utils import fast_keccak


@dataclasses.dataclass(eq=True, frozen=True)
class UserOperationV7:
    """
    EIP4337 UserOperation for Entrypoint v0.7

    https://github.com/eth-infinitism/account-abstraction/blob/v0.7.0/contracts/interfaces/PackedUserOperation.sol
    """

    user_operation_hash: bytes
    sender: ChecksumAddress
    nonce: int
    call_data: bytes
    call_gas_limit: int
    verification_gas_limit: int
    pre_verification_gas: int
    max_priority_fee_per_gas: int
    max_fee_per_gas: int
    signature: bytes
    entry_point: ChecksumAddress
    factory: ChecksumAddress | None = None
    factory_data: bytes | None = None
    paymaster_verification_gas_limit: int | None = None
    paymaster_post_op_gas_limit: int | None = None
    paymaster: bytes | None = None
    paymaster_data: bytes | None = None
    metadata: UserOperationMetadata | None = None

    @property
    def init_code(self) -> bytes:
        """
        Returns the raw init_code bytes (factory address + factory_data).
        For v0.7, this is the concatenation of factory and factory_data.
        """
        if self.factory is not None and self.factory_data is not None:
            return HexBytes(self.factory) + self.factory_data
        else:
            return b""

    @property
    def account_gas_limits(self) -> bytes:
        """
        :return:Account Gas Limits is a `bytes32` in Solidity, first `bytes16` `verification_gas_limit` and then `call_gas_limit`
        """
        return HexBytes(self.verification_gas_limit).rjust(16, b"\x00") + HexBytes(
            self.call_gas_limit
        ).rjust(16, b"\x00")

    @property
    def gas_fees(self) -> bytes:
        """
        :return: Gas Fees is a `bytes32` in Solidity, first `bytes16` `verification_gas_limit` and then `call_gas_limit`
        """
        return HexBytes(self.max_priority_fee_per_gas).rjust(16, b"\x00") + HexBytes(
            self.max_fee_per_gas
        ).rjust(16, b"\x00")

    @property
    def paymaster_and_data(self) -> bytes:
        if (
            not self.paymaster
            or not self.paymaster_verification_gas_limit
            or not self.paymaster_post_op_gas_limit
            or not self.paymaster_data
        ):
            return b""
        return (
            HexBytes(self.paymaster).rjust(20, b"\x00")
            + HexBytes(self.paymaster_verification_gas_limit).rjust(16, b"\x00")
            + HexBytes(self.paymaster_post_op_gas_limit).rjust(16, b"\x00")
            + HexBytes(self.paymaster_data)
        )

    def calculate_user_operation_hash(self, chain_id: int) -> bytes:
        hash_init_code = (
            fast_keccak(self.init_code) if self.init_code else fast_keccak(b"")
        )
        hash_call_data = fast_keccak(self.call_data)
        hash_paymaster_and_data = fast_keccak(self.paymaster_and_data)
        user_operation_encoded = abi_encode(
            [
                "address",
                "uint256",
                "bytes32",
                "bytes32",
                "bytes32",
                "uint256",
                "bytes32",
                "bytes32",
            ],
            [
                self.sender,
                self.nonce,
                hash_init_code,
                hash_call_data,
                self.account_gas_limits,
                self.pre_verification_gas,
                self.gas_fees,
                hash_paymaster_and_data,
            ],
        )
        return fast_keccak(
            abi_encode(
                ["bytes32", "address", "uint256"],
                [fast_keccak(user_operation_encoded), self.entry_point, chain_id],
            )
        )
