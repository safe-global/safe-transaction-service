import logging
from functools import cache
from typing import Optional

from django.conf import settings

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.account_abstraction import BundlerClient
from safe_eth.eth.utils import fast_to_checksum_address
from web3.types import LogReceipt

logger = logging.getLogger(__name__)


@cache
def get_bundler_client() -> Optional[BundlerClient]:
    """
    :return: Initialized `ERC4337 RPC Bundler Client` if configured, `None` otherwise
    """
    if settings.ETHEREUM_4337_BUNDLER_URL:
        return BundlerClient(settings.ETHEREUM_4337_BUNDLER_URL)
    logger.warning("ETHEREUM_4337_BUNDLER_URL not set, cannot configure bundler client")
    return None


def get_user_operation_sender_from_user_operation_log(
    log: LogReceipt,
) -> ChecksumAddress:
    """
    UserOperationEvent (
                    indexed bytes32 userOpHash,
                    indexed address sender,
                    indexed address paymaster,
                    uint256 nonce,
                    bool success,
                    uint256 actualGasCost,
                    uint256 actualGasUsed
                    )
    :param log: `UserOperationEvent` log
    :return: Checksum address of user operation `sender`
    """

    return fast_to_checksum_address(HexBytes(log["topics"][2])[-20:])
