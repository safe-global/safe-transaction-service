"""
ERC4337 Constants

EntryPoint v0.6.0
-----------------
    0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f
    UserOperationEvent (
                        index_topic_1 bytes32 userOpHash, index_topic_2 address sender,
                        index_topic_3 address paymaster, uint256 nonce, bool success,
                        uint256 actualGasCost, uint256 actualGasUsed
                        )
Entrypoint v0.7.0
-----------------
    TBD
"""

from eth_typing import ChecksumAddress, HexAddress, HexStr
from hexbytes import HexBytes

USER_OPERATION_EVENT_TOPICS = {
    HexBytes("0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f")
}

DEPOSIT_EVENT_TOPIC = HexBytes(
    "0x2da466a7b24304f47e87fa2e1e5a81b9831ce54fec19055ce277ca2f39ba42c4"
)

USER_OPERATION_SUPPORTED_ENTRY_POINTS = {
    ChecksumAddress(HexStr(HexAddress("0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789")))
}
