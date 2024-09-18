from dataclasses import dataclass
from typing import List, Sequence

from hexbytes import HexBytes
from safe_eth.eth import EthereumClient
from safe_eth.eth.constants import NULL_ADDRESS

from .kleros_abi import kleros_abi


@dataclass
class KlerosToken:
    name: str
    ticker: str
    address: str
    symbol_multihash: str
    status: int
    number_of_requests: int


class KlerosClient:
    """
    https://github.com/kleros/kleros-interaction/blob/master/contracts/standard/permission/ArbitrableTokenList.sol
    https://github.com/kleros/t2cr-badges-example/blob/master/docs/deep-dive.md
    """

    abi = kleros_abi
    mainnet_address = "0xEbcf3bcA271B26ae4B162Ba560e243055Af0E679"
    null_token_id = b"\x00" * 32  # Empty bytes32 for null tokens

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.kleros_contract = ethereum_client.erc20.slow_w3.eth.contract(
            self.mainnet_address, abi=self.abi
        )

    def get_token_count(self) -> int:
        return self.kleros_contract.functions.tokenCount().call()

    def get_token_ids(self) -> Sequence[bytes]:
        """
        /** @dev Return the values of the tokens the query finds. This function is O(n), where n is the number
        of tokens. This could exceed the gas limit, therefore this function should only be used for interface
        display and not by other contracts.
             *  @param _cursor The ID of the token from which to start iterating. To start from either the oldest
             or newest item.
             *  @param _count The number of tokens to return.
             *  @param _filter The filter to use. Each element of the array in sequence means:
             *  - Include absent tokens in result.
             *  - Include registered tokens in result.
             *  - Include tokens with registration requests that are not disputed in result.
             *  - Include tokens with clearing requests that are not disputed in result.
             *  - Include disputed tokens with registration requests in result.
             *  - Include disputed tokens with clearing requests in result.
             *  - Include tokens submitted by the caller.
             *  - Include tokens challenged by the caller.
             *  @param _oldestFirst Whether to sort from oldest to the newest item.
             *  @param _tokenAddr A token address to filter submissions by address (optional).
             *  @return The values of the tokens found and whether there are more tokens for the current filter and sort.
             */
        """
        token_count = self.get_token_count()
        token_ids: List[bytes]
        has_more: bool
        token_ids, has_more = self.kleros_contract.functions.queryTokens(
            HexBytes("0" * 64),  # bytes32
            token_count,
            [
                False,  # Include absent tokens in result.
                True,  # Include registered tokens in result.
                False,  # Include tokens with registration requests that are not disputed in result.
                False,  # Include tokens with clearing requests that are not disputed in result.
                False,  # Include disputed tokens with registration requests in result.
                False,  # Include disputed tokens with clearing requests in result.
                False,  # Include tokens submitted by the caller.
                False,  # Include tokens challenged by the caller.
            ],
            False,
            NULL_ADDRESS,
        ).call()
        return [token_id for token_id in token_ids if token_id != self.null_token_id]

    def get_token_info(self, token_ids: Sequence[bytes]) -> Sequence[KlerosToken]:
        queries = []
        for token_id in token_ids:
            queries.append(self.kleros_contract.functions.getTokenInfo(token_id))

        # name string, ticker string, addr address, symbolMultihash string, status uint8, numberOfRequests uint256
        token_infos = self.ethereum_client.batch_call(queries)
        return [KlerosToken(*token_info) for token_info in token_infos]

    def get_tokens_with_info(self) -> Sequence[KlerosToken]:
        return self.get_token_info(self.get_token_ids())
