import json
from dataclasses import dataclass
from typing import List, Sequence

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS

abi = json.loads('[{"constant":true,"inputs":[],"name":"challengePeriodDuration","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"governor","outputs":[{"name":"","type":"address"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"arbitratorExtraData","outputs":[{"name":"","type":"bytes"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_beneficiary","type":"address"},{"name":"_request","type":"uint256"}],"name":"amountWithdrawable","outputs":[{"name":"total","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_sharedStakeMultiplier","type":"uint256"}],"name":"changeSharedStakeMultiplier","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_beneficiary","type":"address"},{"name":"_tokenID","type":"bytes32"},{"name":"_cursor","type":"uint256"},{"name":"_count","type":"uint256"},{"name":"_roundCursor","type":"uint256"},{"name":"_roundCount","type":"uint256"}],"name":"batchRequestWithdraw","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"loserStakeMultiplier","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"countByStatus","outputs":[{"name":"absent","type":"uint256"},{"name":"registered","type":"uint256"},{"name":"registrationRequest","type":"uint256"},{"name":"clearingRequest","type":"uint256"},{"name":"challengedRegistrationRequest","type":"uint256"},{"name":"challengedClearingRequest","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_side","type":"uint8"}],"name":"fundAppeal","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"}],"name":"getTokenInfo","outputs":[{"name":"name","type":"string"},{"name":"ticker","type":"string"},{"name":"addr","type":"address"},{"name":"symbolMultihash","type":"string"},{"name":"status","type":"uint8"},{"name":"numberOfRequests","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_disputeID","type":"uint256"},{"name":"_ruling","type":"uint256"}],"name":"rule","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"challengerBaseDeposit","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_requesterBaseDeposit","type":"uint256"}],"name":"changeRequesterBaseDeposit","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_cursor","type":"bytes32"},{"name":"_count","type":"uint256"},{"name":"_filter","type":"bool[8]"},{"name":"_oldestFirst","type":"bool"},{"name":"_tokenAddr","type":"address"}],"name":"queryTokens","outputs":[{"name":"values","type":"bytes32[]"},{"name":"hasMore","type":"bool"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"sharedStakeMultiplier","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"","type":"address"},{"name":"","type":"uint256"}],"name":"arbitratorDisputeIDToTokenID","outputs":[{"name":"","type":"bytes32"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"","type":"uint256"}],"name":"tokensList","outputs":[{"name":"","type":"bytes32"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_request","type":"uint256"},{"name":"_round","type":"uint256"},{"name":"_contributor","type":"address"}],"name":"getContributions","outputs":[{"name":"contributions","type":"uint256[3]"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"arbitrator","outputs":[{"name":"","type":"address"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"metaEvidenceUpdates","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"","type":"address"},{"name":"","type":"uint256"}],"name":"addressToSubmissions","outputs":[{"name":"","type":"bytes32"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_beneficiary","type":"address"},{"name":"_tokenID","type":"bytes32"},{"name":"_request","type":"uint256"},{"name":"_cursor","type":"uint256"},{"name":"_count","type":"uint256"}],"name":"batchRoundWithdraw","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"winnerStakeMultiplier","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_evidence","type":"string"}],"name":"challengeRequest","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},{"constant":true,"inputs":[],"name":"requesterBaseDeposit","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"","type":"bytes32"}],"name":"tokens","outputs":[{"name":"name","type":"string"},{"name":"ticker","type":"string"},{"name":"addr","type":"address"},{"name":"symbolMultihash","type":"string"},{"name":"status","type":"uint8"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_loserStakeMultiplier","type":"uint256"}],"name":"changeLoserStakeMultiplier","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_request","type":"uint256"},{"name":"_round","type":"uint256"}],"name":"getRoundInfo","outputs":[{"name":"appealed","type":"bool"},{"name":"paidFees","type":"uint256[3]"},{"name":"hasPaid","type":"bool[3]"},{"name":"feeRewards","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"tokenCount","outputs":[{"name":"count","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_name","type":"string"},{"name":"_ticker","type":"string"},{"name":"_addr","type":"address"},{"name":"_symbolMultihash","type":"string"}],"name":"requestStatusChange","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},{"constant":false,"inputs":[{"name":"_beneficiary","type":"address"},{"name":"_tokenID","type":"bytes32"},{"name":"_request","type":"uint256"},{"name":"_round","type":"uint256"}],"name":"withdrawFeesAndRewards","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_winnerStakeMultiplier","type":"uint256"}],"name":"changeWinnerStakeMultiplier","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_arbitrator","type":"address"},{"name":"_arbitratorExtraData","type":"bytes"}],"name":"changeArbitrator","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"}],"name":"isPermitted","outputs":[{"name":"allowed","type":"bool"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_request","type":"uint256"}],"name":"getRequestInfo","outputs":[{"name":"disputed","type":"bool"},{"name":"disputeID","type":"uint256"},{"name":"submissionTime","type":"uint256"},{"name":"resolved","type":"bool"},{"name":"parties","type":"address[3]"},{"name":"numberOfRounds","type":"uint256"},{"name":"ruling","type":"uint8"},{"name":"arbitrator","type":"address"},{"name":"arbitratorExtraData","type":"bytes"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_challengePeriodDuration","type":"uint256"}],"name":"changeTimeToChallenge","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"MULTIPLIER_DIVISOR","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_registrationMetaEvidence","type":"string"},{"name":"_clearingMetaEvidence","type":"string"}],"name":"changeMetaEvidence","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_challengerBaseDeposit","type":"uint256"}],"name":"changeChallengerBaseDeposit","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_governor","type":"address"}],"name":"changeGovernor","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_tokenID","type":"bytes32"}],"name":"executeRequest","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_tokenID","type":"bytes32"},{"name":"_evidence","type":"string"}],"name":"submitEvidence","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"_arbitrator","type":"address"},{"name":"_arbitratorExtraData","type":"bytes"},{"name":"_registrationMetaEvidence","type":"string"},{"name":"_clearingMetaEvidence","type":"string"},{"name":"_governor","type":"address"},{"name":"_requesterBaseDeposit","type":"uint256"},{"name":"_challengerBaseDeposit","type":"uint256"},{"name":"_challengePeriodDuration","type":"uint256"},{"name":"_sharedStakeMultiplier","type":"uint256"},{"name":"_winnerStakeMultiplier","type":"uint256"},{"name":"_loserStakeMultiplier","type":"uint256"}],"payable":false,"stateMutability":"nonpayable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":false,"name":"_name","type":"string"},{"indexed":false,"name":"_ticker","type":"string"},{"indexed":false,"name":"_symbolMultihash","type":"string"},{"indexed":true,"name":"_address","type":"address"}],"name":"TokenSubmitted","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_tokenID","type":"bytes32"},{"indexed":false,"name":"_registrationRequest","type":"bool"}],"name":"RequestSubmitted","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_requester","type":"address"},{"indexed":true,"name":"_challenger","type":"address"},{"indexed":true,"name":"_tokenID","type":"bytes32"},{"indexed":false,"name":"_status","type":"uint8"},{"indexed":false,"name":"_disputed","type":"bool"},{"indexed":false,"name":"_appealed","type":"bool"}],"name":"TokenStatusChange","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_tokenID","type":"bytes32"},{"indexed":true,"name":"_contributor","type":"address"},{"indexed":true,"name":"_request","type":"uint256"},{"indexed":false,"name":"_round","type":"uint256"},{"indexed":false,"name":"_value","type":"uint256"}],"name":"RewardWithdrawal","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_metaEvidenceID","type":"uint256"},{"indexed":false,"name":"_evidence","type":"string"}],"name":"MetaEvidence","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_arbitrator","type":"address"},{"indexed":true,"name":"_disputeID","type":"uint256"},{"indexed":false,"name":"_metaEvidenceID","type":"uint256"},{"indexed":false,"name":"_evidenceGroupID","type":"uint256"}],"name":"Dispute","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_arbitrator","type":"address"},{"indexed":true,"name":"_evidenceGroupID","type":"uint256"},{"indexed":true,"name":"_party","type":"address"},{"indexed":false,"name":"_evidence","type":"string"}],"name":"Evidence","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"_arbitrator","type":"address"},{"indexed":true,"name":"_disputeID","type":"uint256"},{"indexed":false,"name":"_ruling","type":"uint256"}],"name":"Ruling","type":"event"}]')


@dataclass
class KlerosToken:
    name: str
    ticker: str
    address: str
    symbol_multihash: str
    status: int
    number_of_requests: int


class KlerosClient:
    kleros_mainnet_address = '0xEbcf3bcA271B26ae4B162Ba560e243055Af0E679'
    null_token_id = b'\x00' * 32  # Empty bytes32 for null tokens

    # https://github.com/kleros/kleros-interaction/blob/master/contracts/standard/permission/ArbitrableTokenList.sol
    # https://github.com/kleros/t2cr-badges-example/blob/master/docs/deep-dive.md
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.kleros_contract = ethereum_client.w3.eth.contract(self.kleros_mainnet_address, abi=abi)

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
            b'',
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
            NULL_ADDRESS).call()
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
