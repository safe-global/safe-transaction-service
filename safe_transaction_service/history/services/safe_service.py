import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Union
from django.db.models import F, QuerySet

from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import (get_cpk_factory_contract,
                                  get_proxy_factory_contract)
from gnosis.safe import Safe
from gnosis.safe.safe import SafeInfo

from ..models import (EthereumEvent, EthereumTx, EthereumTxCallType,
                      InternalTx, ModuleTransaction, MultisigTransaction)

logger = logging.getLogger(__name__)


class SafeServiceException(Exception):
    pass


EthereumAddress = str


@dataclass
class SafeCreationInfo:
    created: datetime
    creator: EthereumAddress
    factory_address: EthereumAddress
    master_copy: Optional[EthereumAddress]
    setup_data: Optional[bytes]
    transaction_hash: str


class SafeServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeService(EthereumClientProvider())

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        dummy_w3 = Web3()  # Not needed, just used to decode contracts
        self.proxy_factory_contract = get_proxy_factory_contract(dummy_w3)
        self.cpk_proxy_factory_contract = get_cpk_factory_contract(dummy_w3)

    def get_all_tx_hashes(self, safe_address: str) -> List[str]:
        """
        Build a queryset with hashes for every tx for a Safe for pagination filtering. In the case of
        Multisig Transactions, as some of them are not mined, we use the SafeTxHash
        :return: List with tx hashes sorted by date (newest first)
        """
        multisig_safe_tx_ids = MultisigTransaction.objects.filter(
            safe=safe_address
        ).annotate(
            execution_date=F('ethereum_tx__block__timestamp')
        ).values('safe_tx_hash', 'execution_date')  # Tricky, we will merge SafeTx hashes with EthereumTx hashes

        # Get incoming tokens
        event_tx_ids = EthereumEvent.objects.erc20_and_721_events().filter(
            arguments__to=safe_address
        ).annotate(
            execution_date=F('ethereum_tx__block__timestamp')
        ).distinct().values('ethereum_tx_id', 'execution_date')

        # Get incoming txs
        internal_tx_ids = InternalTx.objects.filter(
            call_type=EthereumTxCallType.CALL.value,
            value__gt=0,
            to=safe_address,
        ).annotate(
            execution_date=F('ethereum_tx__block__timestamp')
        ).distinct().values('ethereum_tx_id', 'execution_date')

        # Get module txs
        module_tx_ids = ModuleTransaction.objects.filter(
            safe=safe_address
        ).annotate(
            execution_date=F('internal_tx__ethereum_tx__block__timestamp')
        ).distinct().values('internal_tx__ethereum_tx_id', 'execution_date')

        # Tricky, we merge SafeTx hashes with EthereumTx hashes
        queryset = multisig_safe_tx_ids.distinct().union(
            event_tx_ids
        ).union(
            internal_tx_ids
        ).union(
            internal_tx_ids
        ).union(
            module_tx_ids
        ).order_by('-execution_date')
        return list(queryset.values_list('safe_tx_hash', flat=True))

    def get_all_txs_from_hashes(self, safe_address: str, hashes_to_search: List[str]):
        """
        Now that we know how to paginate, we retrieve the real transactions
        :param safe_address:
        :param hashes_to_search:
        :return:
        """
        last_nonce = MultisigTransaction.objects.last_nonce(safe_address)
        if last_nonce is None:
            # No multisig txs
            pass
        else:
            current_nonce = last_nonce + 1

        multisig_txs = MultisigTransaction.objects.filter(
            safe=safe_address,
            nonce__lt=current_nonce,
            safe_tx_hash__in=hashes_to_search
        ).with_confirmations_required(
        ).prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx__block'
        ).order_by(
            '-nonce',
            '-created'
        )

        tokens_queryset = InternalTx.objects.token_incoming_txs_for_address(safe_address).filter(
            ethereum_tx__in=hashes_to_search)
        ether_queryset = InternalTx.objects.ether_incoming_txs_for_address(safe_address).filter(
            ethereum_tx__in=hashes_to_search)
        transfers = list(InternalTx.objects.union_ether_and_token_txs(tokens_queryset, ether_queryset))
        module_txs = list(ModuleTransaction.objects.filter(
            safe=safe_address,
            internal_tx__ethereum_tx__in=hashes_to_search
        ).select_related('internal_tx'))
        plain_ethereum_txs = list(EthereumTx.objects.filter(tx_hash__in=hashes_to_search))

        # Build the list
        def get_the_transaction(h: str):
            # TODO Don't allow duplicates
            multisig_tx: MultisigTransaction
            result = None
            for multisig_tx in multisig_txs:
                if h == multisig_tx.safe_tx_hash or h == multisig_tx.ethereum_tx_id:
                    result = multisig_tx
                    # Populate transfers
                    result.transfers = [transfer for transfer in transfers
                                        if result.ethereum_tx_id == transfer['transaction_hash']]
                    return result

            module_tx: ModuleTransaction
            for module_tx in module_txs:
                if h == module_tx.internal_tx.ethereum_tx_id:
                    result = module_tx
                    result.transfers = [transfer for transfer in transfers
                                        if result.internal_tx.ethereum_tx_id == transfer['transaction_hash']]
                    return result

            plain_ethereum_tx: EthereumTx
            for plain_ethereum_tx in plain_ethereum_txs:
                if h == plain_ethereum_tx.tx_hash:
                    result = plain_ethereum_tx
                    result.transfers = [transfer for transfer in transfers
                                        if result.tx_hash == transfer['transaction_hash']]
                    return result

            # This cannot happen if logic is ok
            if not result:
                raise ValueError('Tx not found, problem merging all transactions together')

        return [get_the_transaction(hash_to_search)
                for hash_to_search in hashes_to_search]  # Sorted already by execution_date

    def get_safe_creation_info(self, safe_address: str) -> Optional[SafeCreationInfo]:
        try:
            creation_internal_tx = InternalTx.objects.select_related('ethereum_tx__block'
                                                                     ).get(contract_address=safe_address)
            previous_internal_tx = creation_internal_tx.get_previous_trace()
            created = creation_internal_tx.ethereum_tx.block.timestamp
            creator = (previous_internal_tx or creation_internal_tx)._from
            proxy_factory = creation_internal_tx._from

            master_copy = None
            setup_data = None
            if previous_internal_tx:
                data = previous_internal_tx.data.tobytes()
                result = self._decode_proxy_factory(data) or self._decode_cpk_proxy_factory(data)
                if result:
                    master_copy, setup_data = result
        except InternalTx.DoesNotExist:
            return None

        return SafeCreationInfo(created, creator, proxy_factory, master_copy, setup_data,
                                creation_internal_tx.ethereum_tx_id)

    def get_safe_info(self, safe_address: str) -> SafeInfo:
        safe = Safe(safe_address, self.ethereum_client)
        return safe.retrieve_all_info()

    def _decode_proxy_factory(self, data: Union[bytes, str]) -> Optional[Tuple[str, bytes]]:
        try:
            _, decoded_data = self.proxy_factory_contract.decode_function_input(data)
            master_copy = decoded_data.get('masterCopy', decoded_data.get('_mastercopy'))
            setup_data = decoded_data.get('data', decoded_data.get('initializer'))
            return master_copy, setup_data
        except ValueError:
            return None

    def _decode_cpk_proxy_factory(self, data) -> Optional[Tuple[str, bytes]]:
        try:
            _, decoded_data = self.cpk_proxy_factory_contract.decode_function_input(data)
            master_copy = decoded_data.get('masterCopy')
            setup_data = decoded_data.get('data')
            return master_copy, setup_data
        except ValueError:
            return None
