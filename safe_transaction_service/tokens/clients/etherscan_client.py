from dataclasses import dataclass
from typing import ClassVar, List, Literal, Sequence

from eth_utils import to_checksum_address


@dataclass
class EtherscanToken:
    name: str
    address: str
    etherscan_url: str


class EtherscanClient:
    tokens_url: ClassVar[str] = 'https://etherscan.io/tokens'

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
