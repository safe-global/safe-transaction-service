from functools import cached_property
from logging import getLogger
from typing import List, Optional, Sequence

from web3.contract import ContractEvent
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import (
    get_proxy_factory_contract,
    get_proxy_factory_V1_1_1_contract,
)

from ..models import ProxyFactory, SafeContract
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class ProxyFactoryIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = ProxyFactoryIndexer(
                EthereumClient(settings.ETHEREUM_NODE_URL)
            )

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class ProxyFactoryIndexer(EventsIndexer):
    @cached_property
    def contract_events(self) -> List[ContractEvent]:
        old_proxy_factory_contract = get_proxy_factory_V1_1_1_contract(
            self.ethereum_client.w3
        )
        proxy_factory_contract = get_proxy_factory_contract(self.ethereum_client.w3)
        return [
            old_proxy_factory_contract.events.ProxyCreation(),
            proxy_factory_contract.events.ProxyCreation(),
        ]

    @property
    def database_field(self):
        return "tx_block_number"

    @property
    def database_queryset(self):
        return ProxyFactory.objects.all()

    def _process_decoded_element(
        self, decoded_element: EventData
    ) -> Optional[SafeContract]:
        contract_address = decoded_element["args"]["proxy"]
        if contract_address != NULL_ADDRESS:
            if (block_number := decoded_element["blockNumber"]) == 0:
                transaction_hash = decoded_element["transactionHash"].hex()
                log_msg = (
                    f"Events are reporting blockNumber=0 for tx-hash={transaction_hash}"
                )
                logger.error(log_msg)
                raise ValueError(log_msg)

            blocks_one_day = int(24 * 60 * 60 / 15)  # 15 seconds block
            return SafeContract(
                address=contract_address,
                ethereum_tx_id=decoded_element["transactionHash"],
                erc20_block_number=max(block_number - blocks_one_day, 0),
            )

    def process_elements(
        self, log_receipts: Sequence[LogReceipt]
    ) -> List[SafeContract]:
        """
        Process all logs

        :param log_receipts: Iterable of Events fetched using `web3.eth.getLogs`
        :return: List of `SafeContract` already stored in database
        """
        safe_contracts = super().process_elements(log_receipts)
        if safe_contracts:
            SafeContract.objects.bulk_create(safe_contracts, ignore_conflicts=True)
        return safe_contracts
