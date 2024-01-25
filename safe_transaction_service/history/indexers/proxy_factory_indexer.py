from functools import cached_property
from logging import getLogger
from typing import List, Optional, Sequence

from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import (
    get_proxy_factory_V1_1_1_contract,
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
)

from ..models import ProxyFactory, SafeContract
from .events_indexer import EventsIndexer

logger = getLogger(__name__)


class ProxyFactoryIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls.get_new_instance()

        return cls.instance

    @classmethod
    def get_new_instance(cls) -> "ProxyFactoryIndexer":
        from django.conf import settings

        return ProxyFactoryIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class ProxyFactoryIndexer(EventsIndexer):
    @cached_property
    def contract_events(self) -> List[ContractEvent]:
        proxy_factory_v1_1_1_contract = get_proxy_factory_V1_1_1_contract(
            self.ethereum_client.w3
        )
        proxy_factory_v1_3_0_contract = get_proxy_factory_V1_3_0_contract(
            self.ethereum_client.w3
        )
        proxy_factory_v_1_4_1_contract = get_proxy_factory_V1_4_1_contract(
            self.ethereum_client.w3
        )
        return [
            # event ProxyCreation(Proxy proxy)
            proxy_factory_v1_1_1_contract.events.ProxyCreation(),
            # event ProxyCreation(GnosisSafeProxy proxy, address singleton)
            proxy_factory_v1_3_0_contract.events.ProxyCreation(),
            # event ProxyCreation(SafeProxy indexed proxy, address singleton)
            proxy_factory_v_1_4_1_contract.events.ProxyCreation(),
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

            return SafeContract(
                address=contract_address,
                ethereum_tx_id=decoded_element["transactionHash"],
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
