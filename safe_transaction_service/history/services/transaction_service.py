import logging
import pickle
import zlib
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from eth_typing import HexStr
from redis import Redis
from safe_eth.eth import EthereumClient, get_auto_ethereum_client

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.utils.redis import get_redis

from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    EthereumTx,
    InternalTx,
    ModuleTransaction,
    MultisigTransaction,
    SafeRelevantTransaction,
    TransferDict,
)
from ..serializers import (
    EthereumTxWithTransfersResponseSerializer,
    SafeModuleTransactionWithTransfersResponseSerializer,
    SafeMultisigTransactionWithTransfersResponseSerializer,
)

logger = logging.getLogger(__name__)


AnySafeTransaction = EthereumTx | MultisigTransaction | ModuleTransaction


class TransactionServiceException(Exception):
    pass


class TransactionServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = TransactionService(get_auto_ethereum_client(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.cache_expiration = settings.CACHE_ALL_TXS_VIEW

    #  Cache methods ---------------------------------
    def get_cache_key(self, safe_address: str, tx_id: str):
        return f"tx-service:{safe_address}:{tx_id}"

    def get_txs_from_cache(
        self, safe_address: str, ids_to_search: Sequence[str]
    ) -> List[AnySafeTransaction]:
        keys_to_search = [
            self.get_cache_key(safe_address, id_to_search)
            for id_to_search in ids_to_search
        ]
        return [
            pickle.loads(zlib.decompress(data)) if data else None
            for data in self.redis.mget(keys_to_search)
        ]

    def store_txs_in_cache(
        self,
        safe_address: str,
        ids_with_txs: Tuple[str, List[AnySafeTransaction]],
    ):
        """
        Store executed transactions older than 10 minutes, using `ethereum_tx_hash` as key (for
        MultisigTransaction it will be `SafeTxHash`) and expire them in one hour

        :param safe_address:
        :param ids_with_txs:
        """
        # Just store executed transactions older than 10 minutes
        to_store = {
            self.get_cache_key(safe_address, tx_hash): zlib.compress(
                pickle.dumps(txs), level=settings.CACHE_ALL_TXS_COMPRESSION_LEVEL
            )
            for tx_hash, txs in ids_with_txs
            if all(
                tx.execution_date
                and (tx.execution_date + timedelta(minutes=10)) < timezone.now()
                for tx in txs
            )
        }
        if to_store:
            pipe = self.redis.pipeline()
            pipe.mset(to_store)
            for key in to_store.keys():
                pipe.expire(key, self.cache_expiration)
            pipe.execute()

    # End of cache methods ----------------------------

    def get_all_tx_identifiers(
        self,
        safe_address: str,
    ) -> QuerySet:
        """
        Build a queryset with all the executed `ethereum transactions` for a Safe for paginated filtering.
        That includes:
        - MultisigTransactions
        - ModuleTransactions
        - ERC20/721 transfers
        - Incoming native token transfers

        :param safe_address:
        :return: Querylist with elements from `SafeRelevantTransaction` model
        """
        logger.debug(
            "[%s] Getting all tx identifiers",
            safe_address,
        )
        return SafeRelevantTransaction.objects.filter(safe=safe_address).order_by(
            "-timestamp", "ethereum_tx_id"
        )

    def get_all_txs_from_identifiers(
        self, safe_address: str, ids_to_search: Sequence[str]
    ) -> List[AnySafeTransaction]:
        """
        Now that we know how to paginate, we retrieve the real transactions

        :param safe_address:
        :param ids_to_search: `SafeTxHash` for MultisigTransactions, `txHash` for other transactions
        :return:
        """

        logger.debug(
            "[%s] Getting %d txs from identifiers", safe_address, len(ids_to_search)
        )
        ids_with_cached_txs = {
            id_to_search: cached_txs
            for id_to_search, cached_txs in zip(
                ids_to_search,
                self.get_txs_from_cache(safe_address, ids_to_search),
            )
            if cached_txs
        }
        logger.debug(
            "[%s] Got %d cached txs from identifiers",
            safe_address,
            len(ids_with_cached_txs),
        )
        ids_not_cached = [
            hash_to_search
            for hash_to_search in ids_to_search
            if hash_to_search not in ids_with_cached_txs
        ]
        logger.debug(
            "[%s] %d not cached txs from identifiers",
            safe_address,
            len(ids_not_cached),
        )
        ids_with_multisig_txs: Dict[HexStr, List[MultisigTransaction]] = {}
        number_multisig_txs = 0
        for multisig_tx in (
            MultisigTransaction.objects.filter(
                safe=safe_address, ethereum_tx_id__in=ids_not_cached
            )
            .with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
            .order_by("-nonce", "-created")
        ):
            ids_with_multisig_txs.setdefault(multisig_tx.ethereum_tx_id, []).append(
                multisig_tx
            )
            number_multisig_txs += 1
        logger.debug(
            "[%s] Got %d Multisig txs from identifiers",
            safe_address,
            number_multisig_txs,
        )

        ids_with_module_txs: Dict[HexStr, List[ModuleTransaction]] = {}
        number_module_txs = 0
        for module_tx in ModuleTransaction.objects.filter(
            safe=safe_address, internal_tx__ethereum_tx__in=ids_not_cached
        ).select_related("internal_tx"):
            ids_with_module_txs.setdefault(
                module_tx.internal_tx.ethereum_tx_id, []
            ).append(module_tx)
            number_module_txs += 1
        logger.debug(
            "[%s] Got %d Module txs from identifiers",
            safe_address,
            number_module_txs,
        )

        ids_with_plain_ethereum_txs: Dict[HexStr, List[EthereumTx]] = {
            ethereum_tx.tx_hash: [ethereum_tx]
            for ethereum_tx in EthereumTx.objects.filter(
                tx_hash__in=ids_not_cached
            ).select_related("block")
        }
        logger.debug(
            "[%s] Got %d Plain Ethereum txs from identifiers",
            safe_address,
            len(ids_with_plain_ethereum_txs),
        )

        # We also need the in/out transfers for the MultisigTxs,
        # add the MultisigTx Ethereum Tx hashes to not cached ids
        all_ids = ids_not_cached + [
            multisig_tx.ethereum_tx_id
            for multisig_txs in ids_with_multisig_txs.values()
            for multisig_tx in multisig_txs
        ]

        erc20_queryset = (
            ERC20Transfer.objects.to_or_from(safe_address)
            .token_txs()
            .filter(ethereum_tx__in=all_ids)
        )
        erc721_queryset = (
            ERC721Transfer.objects.to_or_from(safe_address)
            .token_txs()
            .filter(ethereum_tx__in=all_ids)
        )
        ether_queryset = InternalTx.objects.ether_txs_for_address(safe_address).filter(
            ethereum_tx__in=all_ids
        )

        # Build dict of transfers for optimizing access
        transfer_dict = defaultdict(list)
        transfers: List[TransferDict] = InternalTx.objects.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )
        for transfer in transfers:
            transfer_dict[transfer["transaction_hash"]].append(transfer)

        logger.debug(
            "[%s] Got %d Transfers from identifiers", safe_address, len(transfers)
        )

        # Add available information about the token on database for the transfers
        tokens = {
            token.address: token
            for token in Token.objects.filter(
                address__in={
                    transfer["token_address"]
                    for transfer in transfers
                    if transfer["token_address"]
                }
            )
        }
        logger.debug(
            "[%s] Got %d tokens for transfers from database",
            safe_address,
            len(tokens),
        )

        for transfer in transfers:
            transfer["token"] = tokens.get(transfer["token_address"])

        # Build the list
        def get_the_transactions(
            transaction_id: str,
        ) -> List[MultisigTransaction | ModuleTransaction | EthereumTx]:
            """
            :param transaction_id: SafeTxHash (in case of a ``MultisigTransaction``) or Ethereum ``TxHash`` for the rest
            :return: Transactions for the transaction id, with transfers appended
            """
            if result := ids_with_cached_txs.get(transaction_id):
                return result

            result: Optional[Union[MultisigTransaction, ModuleTransaction, EthereumTx]]
            if result := ids_with_multisig_txs.get(transaction_id):
                for multisig_tx in result:
                    # Populate transfers
                    multisig_tx.transfers = transfer_dict[multisig_tx.ethereum_tx_id]
                return result

            if result := ids_with_module_txs.get(transaction_id):
                for module_tx in result:
                    # Populate transfers
                    module_tx.transfers = transfer_dict[
                        module_tx.internal_tx.ethereum_tx_id
                    ]
                return result

            if result := ids_with_plain_ethereum_txs.get(transaction_id):
                # If no Multisig or Module tx found, fallback to simple tx
                for ethereum_tx in result:
                    # Populate transfers
                    ethereum_tx.transfers = transfer_dict[ethereum_tx.tx_hash]
                return result

            # This cannot happen if logic is ok
            if not result:
                raise ValueError(
                    "Tx not found, problem merging all transactions together"
                )

        logger.debug(
            "[%s] Got all transactions from tx identifiers. Storing in cache",
            safe_address,
        )
        ids_with_txs = [
            (id_to_search, get_the_transactions(id_to_search))
            for id_to_search in ids_to_search
        ]
        self.store_txs_in_cache(safe_address, ids_with_txs)
        logger.debug(
            "[%s] Got all transactions from tx identifiers. Stored in cache",
            safe_address,
        )
        return list(
            dict.fromkeys(tx for (_, txs) in ids_with_txs for tx in txs)
        )  # Sorted already by execution_date

    def serialize_all_txs(
        self, models: List[AnySafeTransaction]
    ) -> List[Dict[str, Any]]:
        logger.debug("Serializing all transactions")
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
                raise ValueError(f"Type={model_type} not expected, cannot serialize")
            serialized = serializer(model)
            # serialized.is_valid(raise_exception=True)
            results.append(serialized.data)

        logger.debug("Serialized all transactions")
        return results
