import json
from dataclasses import dataclass
from functools import cached_property
from typing import (Any, ClassVar, Dict, List, Literal, Optional, Sequence,
                    Union)

from eth_utils import to_checksum_address
from hexbytes import HexBytes
from web3 import Web3


class EtherscanClientException(Exception):
    pass


@dataclass
class BasicEtherscanContract:
    address: str
    abi: Dict[str, Any]
    name: Optional[str]


@dataclass
class EtherscanContract(BasicEtherscanContract):
    code: str
    contract_creation_code: Optional[HexBytes]
    compiler_version: str
    optimization_enabled: str


@dataclass
class EtherscanToken:
    name: str
    address: str
    etherscan_url: str


class EtherscanClient:
    address_url: ClassVar[str] = 'https://etherscan.io/address'
    tokens_url: ClassVar[str] = 'https://etherscan.io/tokens'

    @cached_property
    def scraper(self):
        import cfscrape
        return cfscrape.create_scraper()  # Bypass cloudfare

    def _parse_contracts_page(self, content: bytes) -> Optional[Union[BasicEtherscanContract, EtherscanContract]]:
        from lxml import html

        tree = html.fromstring(content)
        address_xpath = tree.xpath('//*[@id="mainaddress"]')
        if not address_xpath:
            raise EtherscanClientException('Maintenance mode enabled / Rate limit')

        address = Web3.toChecksumAddress(address_xpath[0].text)
        if not tree.xpath('//*[@id="editor"]'):
            if abi_text := tree.xpath('//*[@id="dividcode"]/pre[2]/text()'):
                # Only ABI, like https://etherscan.io/address/0x43892992B0b102459E895B88601Bb2C76736942c
                abi = json.loads(abi_text[0])
                return BasicEtherscanContract(address, abi, None)
            else:
                return None

        name = tree.xpath('//*[@id="ContentPlaceHolder1_contractCodeDiv"]/div[2]/div[1]/div[1]/div[2]/span')[0].text
        code = tree.xpath('//*[@id="editor"]')[0].text_content()
        abi = json.loads(tree.xpath('//*[@id="js-copytextarea2"]')[0].text)
        contract_creation_code_tree = tree.xpath('//*[@id="verifiedbytecode2"]')
        contract_creation_code = HexBytes(contract_creation_code_tree[0].text) if contract_creation_code_tree else None
        compiler_version = tree.xpath('//*[@id="ContentPlaceHolder1_contractCodeDiv"]/div[2]/div[1]/div[2]/div[2]/span')[0].text
        optimization_enabled = tree.xpath('//*[@id="ContentPlaceHolder1_contractCodeDiv"]/div[2]/div[2]/div[1]/div[2]/span')[0].text_content()

        return EtherscanContract(address, abi, name, code, contract_creation_code, compiler_version,
                                 optimization_enabled)

    def _parse_tokens_page(self, content: bytes) -> Sequence[EtherscanToken]:
        from lxml import html
        tree = html.fromstring(content)

        token_data = tree.xpath('//*[@id="tblResult"]/tbody/tr')
        tokens: List[EtherscanToken] = []
        for token in token_data:
            data_element = token.xpath('td[2]/div/div/h3/a')[0]
            name = data_element.text
            etherscan_url = data_element.xpath('@href')[0]
            address = to_checksum_address(etherscan_url.replace('/token/', ''))
            tokens.append(EtherscanToken(name, address, etherscan_url))
        return tokens

    def get_contract_info(self, address: str) -> Optional[EtherscanContract]:
        response = self.scraper.get(f'{self.address_url}/{address}')
        return self._parse_contracts_page(response.content)

    def get_tokens_page(self, page: int = 1,
                        elements: Literal[10, 25, 50, 100] = 100) -> Sequence[EtherscanToken]:
        import cfscrape
        scraper = cfscrape.create_scraper()  # Bypass cloudfare
        response = scraper.get(f'{self.tokens_url}?ps={elements}&p={page}')
        return self._parse_tokens_page(response.content)

    def get_all_tokens(self) -> Sequence[EtherscanToken]:
        all_tokens: List[EtherscanToken] = []
        for page in range(1, 500):
            tokens = self.get_tokens_page(page=page)
            if not tokens:
                break
            else:
                all_tokens.extend(tokens)
        return all_tokens
