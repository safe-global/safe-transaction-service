import logging
import pickle
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from django.conf import settings
from django.db.models import Case, Exists, F, OuterRef, QuerySet, Subquery, Value, When
from django.utils import timezone

from eth_typing import ChecksumAddress, HexStr
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.django.models import Uint256Field

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.utils.redis import get_redis

from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    EthereumTx,
    EthereumTxCallType,
    InternalTx,
    ModuleTransaction,
    MultisigTransaction,
    SafeContract,
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
            cls.instance = TransactionService(EthereumClientProvider(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.redis = redis

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
            pickle.loads(data) if data else None
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
            self.get_cache_key(safe_address, tx_hash): pickle.dumps(txs)
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
                pipe.expire(key, 60 * 60)  # Expire in one hour
            pipe.execute()

    # End of cache methods ----------------------------

    def get_count_relevant_txs_for_safe(self, safe_address: ChecksumAddress) -> int:
        """
        This method searches multiple tables and count every tx or event for a Safe.
        It will return the same or higher value if compared to counting ``get_all_tx_identifiers``
        as that method will group some transactions (for example, 3 ERC20 can be grouped in a ``MultisigTransaction``,
        so it will be ``1`` element for ``get_all_tx_identifiers`` but ``4`` for this function.

        This query should be pretty fast, and it's meant to be used for invalidating caches.

        :param safe_address:
        :return: number of relevant txs for a Safe
        """

        return SafeContract.objects.get_count_relevant_txs_for_safe(safe_address)

    def get_all_tx_identifiers(
        self,
        safe_address: str,
        executed: bool = False,
        queued: bool = True,
        trusted: bool = True,
    ) -> QuerySet:
        """
        Build a queryset with identifiers (`safeTxHash` or `txHash`) for every tx for a Safe for paginated filtering.
        In the case of Multisig Transactions, as some of them are not mined, we use the `safeTxHash`.
        Criteria for building this list:
          - Return ``SafeTxHash`` for every MultisigTx (even not executed)
          - The endpoint should only show incoming transactions that have been mined
          - The transactions should be sorted by execution date. If an outgoing transaction doesn't have an execution
          date the execution date of the transaction with the same nonce that has been executed should be taken.
          - Incoming and outgoing transfers or Eth/tokens must be under a Multisig/Module Tx if triggered by one.
          Otherwise they should have their own entry in the list using a EthereumTx

        :param safe_address:
        :param executed: By default `False`, all transactions are returned. With `True`, just txs executed are returned.
        :param queued: By default `True`, all transactions are returned. With `False`, just txs with
        `nonce < current Safe Nonce` are returned.
        :param trusted: By default `True`, just txs that are trusted are returned (with at least one confirmation,
        sent by a delegate or indexed). With `False` all txs are returned
        :return: List with tx hashes sorted by date (newest first)
        """
        logger.debug(
            "Safe=%s Getting all tx identifiers executed=%s queued=%s trusted=%s",
            safe_address,
            executed,
            queued,
            trusted,
        )
        # If tx is not mined, get the execution date of a tx mined with the same nonce
        case = Case(
            When(
                ethereum_tx__block=None,
                then=MultisigTransaction.objects.filter(
                    safe=OuterRef("safe"), nonce=OuterRef("nonce")
                )
                .exclude(ethereum_tx__block=None)
                .values("ethereum_tx__block__timestamp"),
            ),
            default=F("ethereum_tx__block__timestamp"),
        )
        multisig_safe_tx_ids = (
            MultisigTransaction.objects.filter(safe=safe_address)
            .annotate(
                execution_date=case,
                block=F("ethereum_tx__block_id"),
                safe_nonce=F("nonce"),
            )
            .values(
                "safe_tx_hash",  # Tricky, we will merge SafeTx hashes with EthereumTx hashes
                "execution_date",
                "created",
                "block",
                "safe_nonce",
            )
            .order_by("-execution_date")
        )
        # Block is needed to get stable ordering

        if not queued:  # Filter out txs with nonce >= Safe nonce
            last_nonce_query = (
                MultisigTransaction.objects.filter(safe=safe_address)
                .executed()
                .order_by("-nonce")
                .values("nonce")
            )
            multisig_safe_tx_ids = multisig_safe_tx_ids.filter(
                nonce__lte=Subquery(last_nonce_query[:1])
            )

        if trusted:  # Just show trusted transactions
            multisig_safe_tx_ids = multisig_safe_tx_ids.trusted()

        if executed:
            multisig_safe_tx_ids = multisig_safe_tx_ids.executed()

        # Get module txs
        module_tx_ids = (
            ModuleTransaction.objects.filter(safe=safe_address)
            .annotate(
                execution_date=F("internal_tx__timestamp"),
                block=F("internal_tx__block_number"),
                safe_nonce=Value(0, output_field=Uint256Field()),
            )
            .values(
                "internal_tx__ethereum_tx_id",
                "execution_date",
                "created",
                "block",
                "safe_nonce",
            )
            .order_by("-execution_date")
        )

        multisig_hashes = MultisigTransaction.objects.filter(
            safe=safe_address, ethereum_tx_id=OuterRef("ethereum_tx_id")
        )
        module_hashes = ModuleTransaction.objects.filter(
            safe=safe_address, internal_tx__ethereum_tx_id=OuterRef("ethereum_tx_id")
        )

        # Get incoming/outgoing tokens not included on Multisig or Module txs.
        # Outgoing tokens can be triggered by another user after the Safe calls `approve`, that's why it will not
        # always appear as a MultisigTransaction
        erc20_tx_ids = (
            ERC20Transfer.objects.to_or_from(safe_address)
            .exclude(Exists(multisig_hashes))
            .exclude(Exists(module_hashes))
            .annotate(
                execution_date=F("timestamp"),
                created=F("timestamp"),
                block=F("block_number"),
                safe_nonce=Value(0, output_field=Uint256Field()),
            )
            .values(
                "ethereum_tx_id", "execution_date", "created", "block", "safe_nonce"
            )
            .distinct()
            .order_by("-execution_date")[
                : settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS
            ]
        )

        erc721_tx_ids = (
            ERC721Transfer.objects.to_or_from(safe_address)
            .exclude(Exists(multisig_hashes))
            .exclude(Exists(module_hashes))
            .annotate(
                execution_date=F("timestamp"),
                created=F("timestamp"),
                block=F("block_number"),
                safe_nonce=Value(0, output_field=Uint256Field()),
            )
            .values(
                "ethereum_tx_id", "execution_date", "created", "block", "safe_nonce"
            )
            .distinct()
            .order_by("-execution_date")[
                : settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS
            ]
        )

        # Get incoming ether txs not included on Multisig or Module txs
        internal_tx_ids = (
            InternalTx.objects.filter(
                call_type=EthereumTxCallType.CALL.value,
                value__gt=0,
                to=safe_address,
            )
            .exclude(Exists(multisig_hashes))
            .exclude(Exists(module_hashes))
            .annotate(
                execution_date=F("timestamp"),
                created=F("timestamp"),
                block=F("block_number"),
                safe_nonce=Value(0, output_field=Uint256Field()),
            )
            .values(
                "ethereum_tx_id", "execution_date", "created", "block", "safe_nonce"
            )
            .distinct()
            .order_by("-execution_date")[
                : settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS
            ]
        )

        # Tricky, we merge SafeTx hashes with EthereumTx hashes
        queryset = (
            multisig_safe_tx_ids.union(erc20_tx_ids, all=True)
            .union(erc721_tx_ids, all=True)
            .union(internal_tx_ids, all=True)
            .union(module_tx_ids, all=True)
            .order_by("-execution_date", "-safe_nonce", "block", "-created")
        )
        # Order by block because `block_number < NULL`, so txs mined will have preference,
        # and `created` to get always the same ordering with not executed transactions, as they will share
        # the same `execution_date` that the mined tx
        return queryset

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
            "Safe=%s Getting %d txs from identifiers", safe_address, len(ids_to_search)
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
            "Safe=%s Got %d cached txs from identifiers",
            safe_address,
            len(ids_with_cached_txs),
        )
        ids_not_cached = [
            hash_to_search
            for hash_to_search in ids_to_search
            if hash_to_search not in ids_with_cached_txs
        ]
        logger.debug(
            "Safe=%s %d not cached txs from identifiers",
            safe_address,
            len(ids_not_cached),
        )
        ids_with_multisig_txs: Dict[HexStr, List[MultisigTransaction]] = {
            multisig_tx.safe_tx_hash: [multisig_tx]
            for multisig_tx in MultisigTransaction.objects.filter(
                safe=safe_address, safe_tx_hash__in=ids_not_cached
            )
            .with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
            .order_by("-nonce", "-created")
        }
        logger.debug(
            "Safe=%s Got %d Multisig txs from identifiers",
            safe_address,
            len(ids_with_multisig_txs),
        )

        ids_with_module_txs: Dict[HexStr, List[ModuleTransaction]] = {}
        for module_tx in ModuleTransaction.objects.filter(
            safe=safe_address, internal_tx__ethereum_tx__in=ids_not_cached
        ).select_related("internal_tx"):
            ids_with_module_txs.setdefault(
                module_tx.internal_tx.ethereum_tx_id, []
            ).append(module_tx)
        logger.debug(
            "Safe=%s Got %d Module txs from identifiers",
            safe_address,
            len(ids_with_module_txs),
        )

        ids_with_plain_ethereum_txs: Dict[HexStr, List[EthereumTx]] = {
            ethereum_tx.tx_hash: [ethereum_tx]
            for ethereum_tx in EthereumTx.objects.filter(
                tx_hash__in=ids_not_cached
            ).select_related("block")
        }
        logger.debug(
            "Safe=%s Got %d Plain Ethereum txs from identifiers",
            safe_address,
            len(ids_with_plain_ethereum_txs),
        )

        # We also need the in/out transfers for the MultisigTxs, we add the MultisigTx Ethereum Tx hashes
        # to not cached ids
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
            "Safe=%s Got %d Transfers from identifiers", safe_address, len(transfers)
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
            "Safe=%s Got %d tokens for transfers from database",
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
            "Safe=%s Got all transactions from tx identifiers. Storing in cache",
            safe_address,
        )
        ids_with_txs = [
            (id_to_search, get_the_transactions(id_to_search))
            for id_to_search in ids_to_search
        ]
        self.store_txs_in_cache(safe_address, ids_with_txs)
        logger.debug(
            "Safe=%s Got all transactions from tx identifiers. Stored in cache",
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
