from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

import requests
from cache_memoize import cache_memoize
from hexbytes import HexBytes


class EnsClient:
    def __init__(self, network_id: int):
        base_url = 'https://api.thegraph.com/subgraphs/name/ensdomains/'
        if network_id == 3:  # Ropsten
            url = base_url + 'ensropsten'
        elif network_id == 4:  # Rinkeby
            url = base_url + 'ensrinkeby'
        elif network_id == 5:  # Goerli
            url = base_url + 'ensgoerli'
        else:  # Fallback to mainnet
            url = base_url + 'ens'
        self.url: str = url
        self.request_timeout = 5  # Seconds
        self.request_session = requests.Session()

    def is_available(self):
        """
        :return: True if service is available, False if it's down
        """
        try:
            return not self.request_session.get(self.url, timeout=self.request_timeout).ok
        except IOError:
            return False

    @staticmethod
    def domain_hash_to_hex_str(domain_hash: Union[str, bytes, int]) -> str:
        """
        :param domain_hash:
        :return: Domain hash as an hex string of 66 chars (counting with 0x), padding with zeros if needed
        """
        if not domain_hash:
            domain_hash = b''
        return '0x' + HexBytes(domain_hash).hex()[2:].rjust(64, '0')

    @lru_cache
    @cache_memoize(60 * 60 * 24, prefix='ens-_query_by_domain_hash')  # 1 day
    def _query_by_domain_hash(self, domain_hash_str: str) -> Optional[str]:
        query = """
                {
                    domains(where: {labelhash: "domain_hash"}) {
                        labelName
                    }
                }
                """.replace('domain_hash', domain_hash_str)
        try:
            r = self.request_session.post(self.url, json={'query': query}, timeout=self.request_timeout)
        except IOError:
            return None

        if not r.ok:
            return None
        else:
            """Example:
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
            data = r.json()
            if data:
                domains = data.get('data', {}).get('domains')
                if domains:
                    return domains[0].get('labelName')

    def query_by_domain_hash(self, domain_hash: Union[str, bytes, int]) -> Optional[str]:
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
                        "labelName": "uxio",
                        "labelhash": "0xaa4c58f9a1044bd2936d4bb029ac36ddbc4e0129665fddff8534635a61cdd2be",
                        "name": "uxio.eth",
                        "parent": {
                            "name": "eth"
                        }
                    },
                    "expiryDate": "1905460880"
                }
            ]
        }
        """
        query = '''query getRegistrations {
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
        }'''.replace('account_id', account.lower())
        try:
            r = self.request_session.post(self.url, json={'query': query}, timeout=self.request_timeout)
        except IOError:
            return None

        if not r.ok:
            return None
        else:
            """
             {
                "data": {
                    "account": {
                        "registrations": [
                            {
                                "domain": {
                                    "isMigrated": true,
                                    "labelName": "uxio",
                                    "labelhash": "0xaa4c58f9a1044bd2936d4bb029ac36ddbc4e0129665fddff8534635a61cdd2be",
                                    "name": "uxio.eth",
                                    "parent": {
                                        "name": "eth"
                                    }
                                },
                                "expiryDate": "1905460880"
                            }
                        ]
                    }
                }
            }
            """
            data = r.json()
            if data:
                return data.get('data', {}).get('account')
