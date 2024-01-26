from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

import requests
from cache_memoize import cache_memoize
from hexbytes import HexBytes

from gnosis.eth import EthereumNetwork


# TODO Move this class to safe-eth-py
class EnsClient:
    def __init__(self, network_id: int):
        self.ethereum_network = EthereumNetwork(network_id)
        if network_id == self.ethereum_network.SEPOLIA:
            url = (
                "https://api.studio.thegraph.com/proxy/49574/enssepolia/version/latest/"
            )
        else:  # Fallback to mainnet
            url = "https://api.thegraph.com/subgraphs/name/ensdomains/ens/"
        self.url = url
        self.request_timeout = 5  # Seconds
        self.request_session = requests.Session()

    def is_available(self):
        """
        :return: True if service is available, False if it's down
        """
        try:
            return self.request_session.get(self.url, timeout=self.request_timeout).ok
        except IOError:
            return False

    @staticmethod
    def domain_hash_to_hex_str(domain_hash: Union[str, bytes, int]) -> str:
        """
        :param domain_hash:
        :return: Domain hash as an hex string of 66 chars (counting with 0x), padding with zeros if needed
        """
        if not domain_hash:
            domain_hash = b""
        return "0x" + HexBytes(domain_hash).hex()[2:].rjust(64, "0")

    @lru_cache
    @cache_memoize(60 * 60 * 24, prefix="ens-_query_by_domain_hash")  # 1 day
    def _query_by_domain_hash(self, domain_hash_str: str) -> Optional[str]:
        query = """
                {
                    domains(where: {labelhash: "domain_hash"}) {
                        labelName
                    }
                }
                """.replace(
            "domain_hash", domain_hash_str
        )
        try:
            response = self.request_session.post(
                self.url, json={"query": query}, timeout=self.request_timeout
            )
        except IOError:
            return None

        """
        Example:
        {
            "data": {
                "domains": [
                    {
                        "labelName": "safe-multisig"
                    }
                ]
            }
        }
        """
        if response.ok:
            data = response.json()
            if data:
                domains = data.get("data", {}).get("domains")
                if domains:
                    return domains[0].get("labelName")
        return None

    def query_by_domain_hash(
        self, domain_hash: Union[str, bytes, int]
    ) -> Optional[str]:
        """
        Get domain label from domain_hash (keccak of domain name without the TLD, don't confuse with namehash)
        used for ENS ERC721 token_id. Use another method for caching purposes (use same parameter type)

        :param domain_hash: keccak of domain name without the TLD, don't confuse with namehash. E.g. For
            batman.eth it would be just keccak('batman')
        :return: domain label if found
        """
        domain_hash_str = self.domain_hash_to_hex_str(domain_hash)
        return self._query_by_domain_hash(domain_hash_str)

    def query_by_account(self, account: str) -> Optional[List[Dict[str, Any]]]:
        """
        :param account: ethereum account to search for ENS registered addresses
        :return: None if there's a problem or not found, otherwise example of dictionary returned:
        {
            "registrations": [
                {
                    "domain": {
                        "isMigrated": true,
                        "labelName": "gilfoyle",
                        "labelhash": "0xadfd886b420023026d5c0b1be0ffb5f18bb2f37143dff545aeaea0d23a4ba910",
                        "name": "gilfoyle.eth",
                        "parent": {
                            "name": "eth"
                        }
                    },
                    "expiryDate": "1905460880"
                }
            ]
        }
        """
        query = """query getRegistrations {
          account(id: "account_id") {
            registrations {
              expiryDate
              domain {
                labelName
                labelhash
                name
                isMigrated
                parent {
                  name
                }
              }
            }
          }
        }""".replace(
            "account_id", account.lower()
        )
        try:
            response = self.request_session.post(
                self.url, json={"query": query}, timeout=self.request_timeout
            )
        except IOError:
            return None

        if response.ok:
            data = response.json()
            if data:
                return data.get("data", {}).get("account")
        return None
