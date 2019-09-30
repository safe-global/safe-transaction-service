from logging import getLogger
from typing import Dict, List, Set

from hexbytes import HexBytes
from web3 import Web3
from web3.utils.events import construct_event_topic_set

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_proxy_factory_contract

from ..models import EthereumTx, ProxyFactory, SafeContract
from .transaction_indexer import TransactionIndexer

logger = getLogger(__name__)


class ProxyIndexerServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = ProxyIndexerService(EthereumClient(settings.ETHEREUM_NODE_URL))

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class ProxyIndexerService(TransactionIndexer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_factory_contract = get_proxy_factory_contract(self.ethereum_client.w3)
        self.proxy_creation_topic = construct_event_topic_set(self.proxy_factory_contract.events.ProxyCreation().abi,
                                                              None)[0]

    @property
    def database_field(self):
        return 'tx_block_number'

    @property
    def database_model(self):
        return ProxyFactory

    def find_relevant_elements(self, addresses: List[str], from_block_number: int,
                               to_block_number: int) -> Set[str]:
        """
        Search for tx hashes with erc20 transfer events (`from` and `to`) of a `safe_address`
        :param addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: List of events
        [{'address': '0x12302fE9c02ff50939BaAaaf415fc226C078613C',
          'topics': [HexBytes('0xa38789425dbeee0239e16ff2d2567e31720127fbc6430758c1a4efc6aef29f80')],
          'data': '0x000000000000000000000000d5d4763ae65afffd82e3aee3ec9f21171a1d6e0e',
          'blockNumber': 4835985,
          'transactionHash': HexBytes('0x33733c4be8200d2809d51fd3c99ee6c7564a87a6f102e5cc0abf8d2cc2127abc'),
          'transactionIndex': 2,
          'blockHash': HexBytes('0xcb2bca2285f4f2124761d9ba7ea823a21810b55bc2b24d9d691d23351cad9cd5'),
          'logIndex': 1,
          'removed': False},
         {'address': '0x12302fE9c02ff50939BaAaaf415fc226C078613C',
          'topics': [HexBytes('0xa38789425dbeee0239e16ff2d2567e31720127fbc6430758c1a4efc6aef29f80')],
          'data': '0x0000000000000000000000004cd83a479d8dd5b95eef36f3fc7a7bb9c86699d3',
          'blockNumber': 4840326,
          'transactionHash': HexBytes('0x44cf4dd5bfc4c413420e6ff3280086b9112af21def8d4ea5eeb26aa973975a16'),
          'transactionIndex': 0,
          'blockHash': HexBytes('0x4de2fa52ab9acce800e508cec47b9684240b21bba2f7fca6b5e63acc495f2560'),
          'logIndex': 0,
          'removed': False}
        ]
        """
        logger.debug('Searching for Proxy deployments from block-number=%d to block-number=%d - Proxies=%s',
                     from_block_number, to_block_number, addresses)

        logs = self.ethereum_client.w3.eth.getLogs({'address': addresses,
                                                    'topics': [self.proxy_creation_topic],
                                                    'fromBlock':  from_block_number,
                                                    'toBlock': to_block_number})

        # Log INFO if erc events found, DEBUG otherwise
        logger_fn = logger.info if logs else logger.debug
        logger_fn('Found %d proxy deployments through Proxy Factory between block-number=%d and block-number=%d',
                  len(logs), from_block_number, to_block_number)
        return logs

    def process_element(self, log: Dict[str, any]) -> List[SafeContract]:
        """
        Process every log
        :param log: Log fetched using `web3.eth.getLogs`
        :return: List of `SafeContract` already stored in database
        """
        ethereum_tx = EthereumTx.objects.create_or_update_from_tx_hash(log['transactionHash'])
        int_address = int.from_bytes(HexBytes(log['data']), byteorder='big')
        address = Web3.toChecksumAddress('{:#042x}'.format(int_address))

        # TODO Check `master_copy` address
        if address == NULL_ADDRESS:
            return []
        else:
            return [SafeContract.objects.get_or_create(address=address,
                                                       defaults={
                                                           'ethereum_tx': ethereum_tx,
                                                           # 'initial_block_number': log['blockNumber'],
                                                       })[0]]
