"""
ERC4337 Constants

EntryPoint v0.6.0 and 0.7.0
---------------------------
    0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f
    UserOperationEvent (
                        indexed bytes32 userOpHash,
                        indexed address sender,
                        indexed address paymaster,
                        uint256 nonce,
                        bool success,
                        uint256 actualGasCost,
                        uint256 actualGasUsed
                        )
"""

from hexbytes import HexBytes

USER_OPERATION_NUMBER_TOPICS = 4
USER_OPERATION_EVENT_TOPIC = HexBytes(
    "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"
)
