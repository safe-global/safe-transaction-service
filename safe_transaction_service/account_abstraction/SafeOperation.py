from safe_eth.eth.account_abstraction import UserOperation as UserOperationV6
from safe_eth.eth.utils import fast_keccak
from safe_eth.safe.account_abstraction import SafeOperation as SafeOperationClass

from safe_transaction_service.account_abstraction.UserOperationV7 import UserOperationV7


class SafeOperation(SafeOperationClass):
    @classmethod
    def from_user_operation(cls, user_operation: UserOperationV6 | UserOperationV7):
        return cls(
            user_operation.sender,
            user_operation.nonce,
            fast_keccak(user_operation.init_code),
            fast_keccak(user_operation.call_data),
            user_operation.call_gas_limit,
            user_operation.verification_gas_limit,
            user_operation.pre_verification_gas,
            user_operation.max_fee_per_gas,
            user_operation.max_priority_fee_per_gas,
            fast_keccak(user_operation.paymaster_and_data),
            int.from_bytes(user_operation.signature[:6], byteorder="big"),
            int.from_bytes(user_operation.signature[6:12], byteorder="big"),
            user_operation.entry_point,
            user_operation.signature[12:],
        )
