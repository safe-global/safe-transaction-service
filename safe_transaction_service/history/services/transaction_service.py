import logging
from typing import Any, Dict, List, Union

from django.db.models import Case, F, OuterRef, QuerySet, When, Subquery

from gnosis.eth import EthereumClient, EthereumClientProvider

from ..models import (EthereumEvent, EthereumTx, EthereumTxCallType,
                      InternalTx, ModuleTransaction, MultisigTransaction)
from ..serializers import (
    EthereumTxWithTransfersResponseSerializer,
    SafeModuleTransactionWithTransfersResponseSerializer,
    SafeMultisigTransactionWithTransfersResponseSerializer)

logger = logging.getLogger(__name__)


class TransactionServiceException(Exception):
    pass


class TransactionServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = TransactionService(EthereumClientProvider())

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client

    def get_all_tx_hashes(self, safe_address: str) -> QuerySet:
        """
        Build a queryset with hashes for every tx for a Safe for pagination filtering. In the case of
        Multisig Transactions, as some of them are not mined, we use the SafeTxHash
        :return: List with tx hashes sorted by date (newest first)
        """

        # last_nonce = MultisigTransaction.objects.last_nonce(safe_address)  # None if no Multisig Txs executed
        # current_nonce = 0 if last_nonce is None else last_nonce + 1
        last_nonce_query = MultisigTransaction.objects.filter(
            safe=safe_address
        ).exclude(ethereum_tx=None).order_by('-nonce').values('nonce')

        # If tx is not mined, get the execution date of a tx mined with the same nonce
        case = Case(
            When(ethereum_tx__block=None,
                 then=MultisigTransaction.objects.filter(
                     safe=OuterRef('safe'),
                     nonce=OuterRef('nonce')
                 ).exclude(
                     ethereum_tx__block=None
                 ).values('ethereum_tx__block__timestamp')),
            default=F('ethereum_tx__block__timestamp')
        )
        multisig_safe_tx_ids = MultisigTransaction.objects.annotate(
        ).filter(
            safe=safe_address, nonce__lte=Subquery(last_nonce_query[:1]),
        ).annotate(
            execution_date=case,
            block=F('ethereum_tx__block_id'),
        ).values('safe_tx_hash', 'execution_date', 'block')  # Tricky, we will merge SafeTx hashes with EthereumTx hashes
        # Block is needed to get stable ordering

        # Get incoming tokens
        event_tx_ids = EthereumEvent.objects.erc20_and_721_events().filter(
            arguments__to=safe_address
        ).annotate(
            execution_date=F('ethereum_tx__block__timestamp'),
            block=F('ethereum_tx__block_id'),
        ).distinct().values('ethereum_tx_id', 'execution_date', 'block')

        # Get incoming txs
        internal_tx_ids = InternalTx.objects.filter(
            call_type=EthereumTxCallType.CALL.value,
            value__gt=0,
            to=safe_address,
        ).annotate(
            execution_date=F('ethereum_tx__block__timestamp'),
            block=F('ethereum_tx__block_id'),
        ).distinct().values('ethereum_tx_id', 'execution_date', 'block')

        # Get module txs
        module_tx_ids = ModuleTransaction.objects.filter(
            safe=safe_address
        ).annotate(
            execution_date=F('internal_tx__ethereum_tx__block__timestamp'),
            block=F('internal_tx__ethereum_tx__block_id'),
        ).distinct().values('internal_tx__ethereum_tx_id', 'execution_date', 'block')

        # Tricky, we merge SafeTx hashes with EthereumTx hashes
        queryset = multisig_safe_tx_ids.distinct().union(
            event_tx_ids
        ).union(
            internal_tx_ids
        ).union(
            internal_tx_ids
        ).union(
            module_tx_ids
        ).order_by('-execution_date', 'block', 'safe_tx_hash')
        # Order by safe_tx_hash to get always the same ordering with not executed transactions

        return queryset

    def get_all_txs_from_hashes(self, safe_address: str, hashes_to_search: List[str]) -> List[Union[EthereumTx,
                                                                                                    MultisigTransaction,
                                                                                                    ModuleTransaction]]:
        """
        Now that we know how to paginate, we retrieve the real transactions
        :param safe_address:
        :param hashes_to_search:
        :return:
        """
        multisig_txs = MultisigTransaction.objects.filter(
            safe=safe_address,
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

        module_txs = list(ModuleTransaction.objects.filter(
            safe=safe_address,
            internal_tx__ethereum_tx__in=hashes_to_search
        ).select_related('internal_tx'))
        plain_ethereum_txs = list(EthereumTx.objects.filter(tx_hash__in=hashes_to_search))

        # We also need the out transfers for the MultisigTxs
        all_hashes = hashes_to_search + [multisig_tx.ethereum_tx_id for multisig_tx in multisig_txs]

        tokens_queryset = InternalTx.objects.token_txs_for_address(safe_address).filter(
            ethereum_tx__in=all_hashes)
        ether_queryset = InternalTx.objects.ether_txs_for_address(safe_address).filter(
            ethereum_tx__in=all_hashes)
        transfers = list(InternalTx.objects.union_ether_and_token_txs(tokens_queryset, ether_queryset))

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

        # Remove duplicates
        return list(dict.fromkeys([get_the_transaction(hash_to_search)
                                   for hash_to_search in hashes_to_search]))  # Sorted already by execution_date

    def serialize_all_txs(self, models: List[Union[EthereumTx,
                                                   MultisigTransaction,
                                                   ModuleTransaction]]) -> List[Dict[str, Any]]:
        results = []
        for model in models:
            model_type = type(model)
            if model_type == EthereumTx:
                serializer = EthereumTxWithTransfersResponseSerializer
            elif model_type == ModuleTransaction:
                serializer = SafeModuleTransactionWithTransfersResponseSerializer
            elif model_type == MultisigTransaction:
                serializer = SafeMultisigTransactionWithTransfersResponseSerializer
            else:
                raise ValueError(f'Type={model_type} not expected, cannot serialize')
            serialized = serializer(model)
            # serialized.is_valid(raise_exception=True)
            results.append(serialized.data)
        return results
