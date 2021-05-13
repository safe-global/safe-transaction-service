from collections import OrderedDict
from functools import cached_property
from logging import getLogger
from typing import Dict, List, Optional, Set, Sequence

from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_proxy_factory_contract, get_proxy_factory_V1_1_1_contract
from web3.contract import ContractEvent
from web3.types import EventData, LogReceipt

from ..models import EthereumTx, ProxyFactory, SafeContract
from .ethereum_indexer import EthereumIndexer

logger = getLogger(__name__)


class ProxyFactoryIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = ProxyFactoryIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, 'instance'):
            del cls.instance


class ProxyFactoryIndexer(EthereumIndexer):
    def __init__(self, *args, **kwargs):
        kwargs['first_block_threshold'] = 0
        super().__init__(*args, **kwargs)

    @cached_property
    def events_to_listen(self) -> Dict[bytes, ContractEvent]:
        old_proxy_factory_contract = get_proxy_factory_V1_1_1_contract(self.ethereum_client.w3)
        proxy_factory_contract = get_proxy_factory_contract(self.ethereum_client.w3)
        events = [
            old_proxy_factory_contract.events.ProxyCreation(),
            proxy_factory_contract.events.ProxyCreation(),
        ]
        return {HexBytes(event_abi_to_log_topic(event.abi)).hex(): event for event in events}

    @property
    def database_field(self):
        return 'tx_block_number'

    @property
    def database_model(self):
        return ProxyFactory

    def find_relevant_elements(self, addresses: List[str], from_block_number: int,
                               to_block_number: int,
                               current_block_number: Optional[int] = None) -> Set[str]:
        """
        Search for tx hashes with erc20 transfer events (`from` and `to`) of a `safe_address`
        :param addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :param current_block_number:
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

        filter_topics = list(self.events_to_listen.keys())
        try:
            logs = self.ethereum_client.slow_w3.eth.getLogs({'address': addresses,
                                                             'topics': [filter_topics],
                                                             'fromBlock': from_block_number,
                                                             'toBlock': to_block_number})
        except IOError as e:
            raise self.FindRelevantElementsException('Request error retrieving Safe L2 events') from e

        # Log INFO if erc events found, DEBUG otherwise
        logger_fn = logger.info if logs else logger.debug
        logger_fn('Found %d proxy deployments through Proxy Factory between block-number=%d and block-number=%d',
                  len(logs), from_block_number, to_block_number)
        return logs

    def _process_decoded_element(self, decoded_element: EventData) -> Optional[SafeContract]:
        contract_address = decoded_element['args']['proxy']
        if contract_address != NULL_ADDRESS:
            if (block_number := decoded_element['blockNumber']) == 0:
                transaction_hash = decoded_element['transactionHash'].hex()
                log_msg = f'Events are reporting blockNumber=0 for tx-hash={transaction_hash}'
                logger.error(log_msg)
                raise ValueError(log_msg)

            blocks_one_day = int(24 * 60 * 60 / 15)  # 15 seconds block
            return SafeContract(address=contract_address,
                                ethereum_tx_id=decoded_element['transactionHash'],
                                erc20_block_number=max(block_number - blocks_one_day, 0))

    def process_elements(self, log_receipts: Sequence[LogReceipt]) -> List[SafeContract]:
        """
        Process all logs
        :param log_receipts: Iterable of Events fetched using `web3.eth.getLogs`
        :return: List of `SafeContract` already stored in database
        """
        decoded_elements: List[EventData] = [
            self.events_to_listen[log_receipt['topics'][0].hex()].processLog(log_receipt)
            for log_receipt in log_receipts
        ]
        tx_hashes = OrderedDict.fromkeys([event['transactionHash'] for event in log_receipts]).keys()
        logger.debug('Prefetching and storing %d ethereum txs', len(tx_hashes))
        ethereum_txs = self.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        logger.debug('End prefetching and storing of ethereum txs')
        safe_contracts = [self._process_decoded_element(decoded_element) for decoded_element in decoded_elements]
        safe_contracts = [safe_contract for safe_contract in safe_contracts if safe_contract]
        if safe_contracts:
            SafeContract.objects.bulk_create(safe_contracts, ignore_conflicts=True)
        return safe_contracts
