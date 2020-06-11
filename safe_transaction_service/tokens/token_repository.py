import logging
import os
from typing import Any, List

import requests
from eth_utils import to_checksum_address
from lxml import html

logger = logging.getLogger(__name__)


class TokenRepository:
    def __download_file(self, url: str, taget_folder: str, local_filename: str) -> str:
        if not os.path.exists(taget_folder):
            os.makedirs(taget_folder)
        r = requests.get(url, stream=True)
        if r.status_code != 200:
            logger.warning("Image not found for url %s", url)
            return
        with open(os.path.join(taget_folder, local_filename), 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        return local_filename

    def __pull_token_info(self, page_number: int = 1) -> List[Any]:
        tokens = []
        page = requests.get('https://etherscan.io/tokens?p=' + str(page_number))
        tree = html.fromstring(page.content)

        token_data = tree.xpath('//div[@id="ContentPlaceHolder1_divresult"]/table/tbody/tr')
        for element in token_data:
            link = element.xpath('td[@align="center"]/a/@href')[0]
            token_address = to_checksum_address(link[7:])
            desc = element.xpath('td/small/font/text()')
            token_request = requests.get(
                "https://raw.githubusercontent.com/ethereum-lists/tokens/master/tokens/eth/" + token_address + ".json")
            if token_request.status_code == 200:
                data = token_request.json()
            else:
                logger.info("Not info for token %s, using fallback source", token_address)
                data = self.__token_info_fallback(token_address)

            if data:
                if not data.get('website'):
                    data['website'] = self.__token_website_fallback(token_address)
                data.setdefault('description', desc[0] if desc else '')
                tokens.append(data)
            else:
                logger.warning("Token info not found for token %s", token_address)

        return tokens

    def __token_website_fallback(self, token_address):
        url = 'https://etherscan.io/token/' + token_address
        logger.debug('Falling back for token with address=%s, url=%s', token_address, url)
        page = requests.get(url)
        tree = html.fromstring(page.content)
        website = tree.xpath('//tr[@id="ContentPlaceHolder1_tr_officialsite_1"]/td/a/text()')
        return website[0].strip() if website else ''

    def __token_info_fallback(self, token_address):
        """
        Get token info using ArthurStandardToken interface
        :param token_address:
        :return:
        """
        page = requests.get(
            'https://etherscan.io/readContract?v=0xb9469430eabcbfa77005cd3ad4276ce96bd221e3&a=' + token_address)
        tree = html.fromstring(page.content)
        return {
            "address": token_address,
            "name": tree.xpath(
                '//a[contains(text(), "name")]/../../following-sibling::div//div[@class="form-group"]/text()')[
                0].strip(),
            "symbol": tree.xpath(
                '//a[contains(text(), "symbol")]/../../following-sibling::div//div[@class="form-group"]/text()')[
                0].strip(),
            "decimals": int(tree.xpath(
                '//a[contains(text(), "decimals")]/../../following-sibling::div//div[@class="form-group"]/text()')[
                                0].strip())
        }

    def __get_token_image_url(self, token_address: str) -> str:
        """
        :param token_address:
        :return: token url
        """
        return "https://raw.githubusercontent.com/TrustWallet/tokens/master/images/" + token_address.lower() + ".png"

    def get_tokens(self, pages: int = 1) -> List[Any]:
        all_tokens = []
        for page in range(1, pages + 1):
            all_tokens.extend(self.__pull_token_info(page))

        tokens = [{
            "address": to_checksum_address(token.get('address')),
            "name": token.get('name'),
            "symbol": token.get('symbol'),
            "description": token.get('description'),
            "decimals": token.get('decimals'),
            "logo_url": None,
            "website_url": token.get('website')
        } for token in all_tokens]
        return tokens

    def download_images_for_tokens(self, folder: str, token_addresses: List[str]) -> List[str]:
        token_uris = []
        for token_address in token_addresses:
            token_uri = self.__get_token_image_url(token_address.lower())
            self.__download_file(token_uri, folder, token_address + ".png")
            token_uris.append(token_uri)
        return token_uris


if __name__ == "__main__":
    token_info = TokenRepository()
    token_icons_path = os.path.join("images", "tokens", "mainnet")
    for token in token_info.get_tokens(pages=3):
        print(token)
        token_info.download_images_for_tokens(token_icons_path, token_addresses=[token['address']])
