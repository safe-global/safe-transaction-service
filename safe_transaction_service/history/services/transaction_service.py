import logging
import pickle
import zlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from django.conf import settings
from django.db import connection
from django.db.models import F, QuerySet
from django.db.models.expressions import RawSQL
from django.utils import timezone

from eth_typing import ChecksumAddress, HexStr
from hexbytes import HexBytes
from redis import Redis
from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.eth.utils import fast_to_checksum_address

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
    SafeMultisigTransactionWithTransfersResponseSerializerV2,
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
    ) -> list[AnySafeTransaction]:
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
        ids_with_txs: tuple[str, list[AnySafeTransaction]],
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
    ) -> list[AnySafeTransaction]:
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
        ids_with_multisig_txs: dict[HexStr, list[MultisigTransaction]] = {}
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

        ids_with_module_txs: dict[HexStr, list[ModuleTransaction]] = {}
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

        ids_with_plain_ethereum_txs: dict[HexStr, list[EthereumTx]] = {
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
        transfers: list[TransferDict] = InternalTx.objects.union_ether_and_token_txs(
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
        ) -> list[MultisigTransaction | ModuleTransaction | EthereumTx]:
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
        self, models: list[AnySafeTransaction]
    ) -> list[dict[str, Any]]:
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

    def serialize_all_txs_v2(
        self, models: list[AnySafeTransaction]
    ) -> list[dict[str, Any]]:
        logger.debug("Serializing all transactions")
        results = []
        for model in models:
            model_type = type(model)
            if model_type == EthereumTx:
                serializer = EthereumTxWithTransfersResponseSerializer
            elif model_type == ModuleTransaction:
                serializer = SafeModuleTransactionWithTransfersResponseSerializer
            elif model_type == MultisigTransaction:
                serializer = SafeMultisigTransactionWithTransfersResponseSerializerV2
            else:
                raise ValueError(f"Type={model_type} not expected, cannot serialize")
            serialized = serializer(model)
            # serialized.is_valid(raise_exception=True)
            results.append(serialized.data)

        logger.debug("Serialized all transactions")
        return results

    def get_export_transactions(
        self,
        safe_address: ChecksumAddress,
        execution_date_gte: Optional[datetime] = None,
        execution_date_lte: Optional[datetime] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get transactions optimized for CSV export using raw SQL queries

        :param safe_address: Safe address to get transactions for
        :param execution_date_gte: Filter transactions executed after this date
        :param execution_date_lte: Filter transactions executed before this date
        :param limit: Maximum number of transactions to return
        :param offset: Number of transactions to skip
        :return: Tuple of (transactions, total_count)
        """
        logger.debug(
            "[%s] Getting export transactions with raw SQL: gte=%s, lte=%s, limit=%d, offset=%d",
            safe_address,
            execution_date_gte,
            execution_date_lte,
            limit,
            offset,
        )

        # Base WHERE conditions for the final SELECT
        where_conditions = []
        params = []

        if execution_date_gte:
            assert type(execution_date_gte) is datetime
            where_conditions.append("execution_date >= %s")
            params.append(execution_date_gte)
        if execution_date_lte:
            assert type(execution_date_lte) is datetime
            where_conditions.append("execution_date <= %s")
            params.append(execution_date_lte)

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        # Main query that unions all transaction types with their transfers
        main_query = f"""
        WITH export_data AS (
            -- ERC20 Transfers from multisigtransactions
            SELECT
                encode(mt.safe, 'hex') as safe_address,
                encode(erc20._from, 'hex') as from_address,
                encode(erc20.to, 'hex') as to_address,
                erc20.value::text as amount,
                'erc20' as asset_type,
                encode(erc20.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(et._from, 'hex') as executor_address,
                erc20.timestamp as execution_date,
                erc20.timestamp as executed_at,
                COALESCE(mt.origin->>'note', '') as note,
                encode(mt.ethereum_tx_id, 'hex') as transaction_hash,
                encode(mt.safe_tx_hash, 'hex') as safe_tx_hash,
                null as method,
                encode(mt.to, 'hex') as contract_address,
                COALESCE(erc20.timestamp, mt.created) as sort_date
            FROM history_multisigtransaction mt
            JOIN history_ethereumtx et ON mt.ethereum_tx_id = et.tx_hash
            JOIN history_erc20transfer erc20 ON et.tx_hash = erc20.ethereum_tx_id
            LEFT JOIN tokens_token t ON erc20.address = t.address
            WHERE mt.safe = %s

            UNION ALL

            -- ERC20 Transfers (standalone) incoming, or outgoing with token approval
            SELECT
                encode(CASE
                    WHEN erc20.to = %s THEN erc20.to
                    ELSE erc20._from
                END, 'hex') as safe_address,
                encode(erc20._from, 'hex') as from_address,
                encode(erc20.to, 'hex') as to_address,
                erc20.value::text as amount,
                'erc20' as asset_type,
                encode(erc20.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(et._from, 'hex') as executor_address,
                erc20.timestamp as execution_date,
                erc20.timestamp as executed_at,
                '' as note,
                encode(erc20.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                null as contract_address,
                erc20.timestamp as sort_date
            FROM history_erc20transfer erc20
            JOIN history_ethereumtx et ON erc20.ethereum_tx_id = et.tx_hash
            LEFT JOIN tokens_token t ON erc20.address = t.address
            WHERE (erc20.to = %s OR erc20._from = %s)
            AND NOT EXISTS (
                SELECT 1 FROM history_multisigtransaction mt
                WHERE mt.ethereum_tx_id = erc20.ethereum_tx_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM history_moduletransaction modtx
                JOIN history_internaltx itx ON modtx.internal_tx_id = itx.id
                WHERE itx.ethereum_tx_id = erc20.ethereum_tx_id
            )

            UNION ALL

            -- Multisig Transactions with ERC721 Transfers
            SELECT
                encode(mt.safe, 'hex') as safe_address,
                encode(erc721._from, 'hex') as from_address,
                encode(erc721.to, 'hex') as to_address,
                erc721.token_id::text as amount,
                'erc721' as asset_type,
                encode(erc721.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(et._from, 'hex') as executor_address,
                erc721.timestamp as execution_date,
                erc721.timestamp as executed_at,
                COALESCE(mt.origin->>'note', '') as note,
                encode(mt.ethereum_tx_id, 'hex') as transaction_hash,
                encode(mt.safe_tx_hash, 'hex') as safe_tx_hash,
                null as method,
                encode(mt.to, 'hex') as contract_address,
                COALESCE(erc721.timestamp, mt.created) as sort_date
            FROM history_multisigtransaction mt
            JOIN history_ethereumtx et ON mt.ethereum_tx_id = et.tx_hash
            JOIN history_erc721transfer erc721 ON et.tx_hash = erc721.ethereum_tx_id
            LEFT JOIN tokens_token t ON erc721.address = t.address
            WHERE mt.safe = %s

            UNION ALL

            -- Multisig Transactions (standalone, without transfers)
            SELECT
                encode(mt.safe, 'hex') as safe_address,
                encode(mt.safe, 'hex') as from_address,
                encode(mt.to, 'hex') as to_address,
                itx.value::text as amount,
                'native' as asset_type,
                null as asset_address,
                'ETH' as asset_symbol,
                18 as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(et._from, 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                COALESCE(mt.origin->>'note', '') as note,
                encode(mt.ethereum_tx_id, 'hex') as transaction_hash,
                encode(mt.safe_tx_hash, 'hex') as safe_tx_hash,
                null as method,
                encode(mt.to, 'hex') as contract_address,
                COALESCE(itx.timestamp, mt.created) as sort_date
            FROM history_multisigtransaction mt
            JOIN history_ethereumtx et ON mt.ethereum_tx_id = et.tx_hash
            JOIN history_internaltx itx ON itx.ethereum_tx_id = et.tx_hash
            WHERE mt.safe = %s
            AND itx.call_type = 0  -- CALL
            AND itx.value > 0
            AND NOT EXISTS (
                SELECT 1 FROM history_erc20transfer erc20
                WHERE erc20.ethereum_tx_id = et.tx_hash
            )
            AND NOT EXISTS (
                SELECT 1 FROM history_erc721transfer erc721
                WHERE erc721.ethereum_tx_id = et.tx_hash
            )

            UNION ALL

            -- Module Transactions with ERC20 Transfers
            SELECT
                encode(modtx.safe, 'hex') as safe_address,
                encode(COALESCE(erc20._from, modtx.module), 'hex') as from_address,
                encode(COALESCE(erc20.to, modtx.to), 'hex') as to_address,
                COALESCE(erc20.value::text, modtx.value::text) as amount,
                CASE
                    WHEN erc20.address IS NOT NULL THEN 'erc20'
                    ELSE 'native'
                END as asset_type,
                encode(erc20.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(modtx.module, 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                '' as note,
                encode(itx.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                encode(modtx.to, 'hex') as contract_address,
                itx.timestamp as sort_date
            FROM history_moduletransaction modtx
            JOIN history_internaltx itx ON modtx.internal_tx_id = itx.id
            JOIN history_erc20transfer erc20 ON itx.ethereum_tx_id = erc20.ethereum_tx_id
            LEFT JOIN tokens_token t ON erc20.address = t.address
            WHERE modtx.safe = %s

            UNION ALL

            -- Module Transactions with ERC721 Transfers
            SELECT
                encode(modtx.safe, 'hex') as safe_address,
                encode(COALESCE(erc721._from, modtx.module), 'hex') as from_address,
                encode(COALESCE(erc721.to, modtx.to), 'hex') as to_address,
                COALESCE(erc721.token_id::text, modtx.value::text) as amount,
                CASE
                    WHEN erc721.address IS NOT NULL THEN 'erc721'
                    ELSE 'native'
                END as asset_type,
                encode(erc721.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(modtx.module, 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                '' as note,
                encode(itx.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                encode(modtx.to, 'hex') as contract_address,
                itx.timestamp as sort_date
            FROM history_moduletransaction modtx
            JOIN history_internaltx itx ON modtx.internal_tx_id = itx.id
            JOIN history_erc721transfer erc721 ON itx.ethereum_tx_id = erc721.ethereum_tx_id
            LEFT JOIN tokens_token t ON erc721.address = t.address
            WHERE modtx.safe = %s

            UNION ALL

            -- Module Transactions with ethereum Transfers
            SELECT
                encode(modtx.safe, 'hex') as safe_address,
                encode(COALESCE(itx._from, modtx.module), 'hex') as from_address,
                encode(COALESCE(itx.to, modtx.to), 'hex') as to_address,
                itx.value::text as amount,
               'native' as asset_type,
                null as asset_address,
                'ETH' as asset_symbol,
                18 as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(modtx.module, 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                '' as note,
                encode(itx.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                encode(modtx.to, 'hex') as contract_address,
                itx.timestamp as sort_date
            FROM history_moduletransaction modtx
            JOIN history_internaltx itx ON modtx.internal_tx_id = itx.id
            WHERE itx.to = %s OR itx._from = %s and itx.value > 0
            AND NOT EXISTS (
                SELECT 1 FROM history_erc20transfer erc20
                WHERE erc20.ethereum_tx_id = itx.ethereum_tx_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM history_erc721transfer erc721
                WHERE erc721.ethereum_tx_id = itx.ethereum_tx_id
            )

            UNION ALL

            -- ERC721 Transfers (standalone)
            SELECT
                encode(CASE
                    WHEN erc721.to = %s THEN erc721.to
                    ELSE erc721._from
                END, 'hex') as safe_address,
                encode(erc721._from, 'hex') as from_address,
                encode(erc721.to, 'hex') as to_address,
                erc721.token_id::text as amount,
                'erc721' as asset_type,
                encode(erc721.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(et._from, 'hex') as executor_address,
                erc721.timestamp as execution_date,
                erc721.timestamp as executed_at,
                '' as note,
                encode(erc721.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                null as contract_address,
                erc721.timestamp as sort_date
            FROM history_erc721transfer erc721
            JOIN history_ethereumtx et ON erc721.ethereum_tx_id = et.tx_hash
            LEFT JOIN tokens_token t ON erc721.address = t.address
            WHERE (erc721.to = %s OR erc721._from = %s)
            AND NOT EXISTS (
                SELECT 1 FROM history_multisigtransaction mt
                WHERE mt.ethereum_tx_id = erc721.ethereum_tx_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM history_moduletransaction modtx
                JOIN history_internaltx itx ON modtx.internal_tx_id = itx.id
                WHERE itx.ethereum_tx_id = erc721.ethereum_tx_id
            )

            UNION ALL

            -- Ether Transfers (InternalTx)
            SELECT
                encode(CASE
                    WHEN itx.to = %s THEN itx.to
                    ELSE itx._from
                END, 'hex') as safe_address,
                encode(itx._from, 'hex') as from_address,
                encode(itx.to, 'hex') as to_address,
                itx.value::text as amount,
                'native' as asset_type,
                null as asset_address,
                'ETH' as asset_symbol,
                18 as asset_decimals,
                null as proposer_address,
                null as proposed_at,
                encode(et._from, 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                '' as note,
                encode(itx.ethereum_tx_id, 'hex') as transaction_hash,
                null as safe_tx_hash,
                null as method,
                null as contract_address,
                itx.timestamp as sort_date
            FROM history_internaltx itx
            JOIN history_ethereumtx et ON itx.ethereum_tx_id = et.tx_hash
            WHERE (itx.to = %s OR itx._from = %s)
            AND itx.call_type = 0  -- CALL
            AND itx.value > 0
            AND NOT EXISTS (
                SELECT 1 FROM history_multisigtransaction mt
                WHERE mt.ethereum_tx_id = itx.ethereum_tx_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM history_moduletransaction modtx
                JOIN history_internaltx itx2 ON modtx.internal_tx_id = itx2.id
                WHERE itx2.ethereum_tx_id = itx.ethereum_tx_id
            )
        )
        SELECT
            safe_address,
            from_address,
            to_address,
            amount,
            asset_type,
            asset_address,
            asset_symbol,
            asset_decimals,
            proposer_address,
            proposed_at,
            executor_address,
            execution_date,
            executed_at,
            note,
            transaction_hash,
            safe_tx_hash,
            method,
            contract_address
        FROM export_data
        WHERE {where_clause}
        ORDER BY execution_date DESC, transaction_hash
        LIMIT %s OFFSET %s
        """

        # Parameters for main query (safe_address repeated for each UNION)
        safe_address_bytes = HexBytes(safe_address)
        main_params = (
            [safe_address_bytes] * 16  # 16 instances of safe address in the query
            + params  # date filters
            + [limit, offset]
        )

        erc20_transfers = ERC20Transfer.objects.to_or_from(safe_address)
        erc721_transfers = ERC721Transfer.objects.to_or_from(safe_address)
        ether_transfers = InternalTx.objects.ether_txs_for_address(safe_address)

        if execution_date_gte:
            erc20_transfers = erc20_transfers.filter(timestamp__gte=execution_date_gte)
            erc721_transfers = erc721_transfers.filter(
                timestamp__gte=execution_date_gte
            )
            ether_transfers = ether_transfers.filter(timestamp__gte=execution_date_gte)
        if execution_date_lte:
            erc20_transfers = erc20_transfers.filter(timestamp__lte=execution_date_lte)
            erc721_transfers = erc721_transfers.filter(
                timestamp__lte=execution_date_lte
            )
            ether_transfers = ether_transfers.filter(timestamp__lte=execution_date_lte)

        erc20_transfers = erc20_transfers.annotate(
            transaction_hash=F("ethereum_tx_id"),
            _log_index=F("log_index"),
            _trace_address=RawSQL("NULL", ()),
        ).values("transaction_hash", "_log_index", "_trace_address")
        erc721_transfers = erc721_transfers.annotate(
            transaction_hash=F("ethereum_tx_id"),
            _log_index=F("log_index"),
            _trace_address=RawSQL("NULL", ()),
        ).values("transaction_hash", "_log_index", "_trace_address")
        ether_transfers = ether_transfers.annotate(
            transaction_hash=F("ethereum_tx_id"),
            _log_index=RawSQL("NULL::numeric", ()),
            _trace_address=F("trace_address"),
        ).values("transaction_hash", "_log_index", "_trace_address")

        total_count = (
            ether_transfers.union(erc20_transfers, all=True)
            .union(erc721_transfers, all=True)
            .count()
        )

        with connection.cursor() as cursor:

            # Get the data
            cursor.execute(main_query, main_params)
            columns = [col[0] for col in cursor.description]
            results = []

            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))

                # Map to serializer field names
                export_item = {
                    "safe": fast_to_checksum_address(row_dict["safe_address"]),
                    "_from": fast_to_checksum_address(row_dict["from_address"]),
                    "to": fast_to_checksum_address(row_dict["to_address"]),
                    "_value": row_dict["amount"],
                    "asset_type": row_dict["asset_type"],
                    "asset_address": (
                        fast_to_checksum_address(row_dict["asset_address"])
                        if row_dict["asset_address"]
                        else None
                    ),
                    "asset_symbol": (
                        row_dict["asset_symbol"] if row_dict["asset_symbol"] else None
                    ),
                    "asset_decimals": (
                        row_dict["asset_decimals"]
                        if row_dict["asset_decimals"]
                        else None
                    ),
                    "proposer_address": (
                        fast_to_checksum_address(row_dict["proposer_address"])
                        if row_dict["proposer_address"]
                        else None
                    ),
                    "proposed_at": (
                        row_dict["proposed_at"] if row_dict["proposed_at"] else None
                    ),
                    "executor_address": (
                        fast_to_checksum_address(row_dict["executor_address"])
                        if row_dict["executor_address"]
                        else None
                    ),
                    "executed_at": (
                        row_dict["executed_at"] if row_dict["executed_at"] else None
                    ),
                    "note": row_dict["note"] if row_dict["note"] else None,
                    "transaction_hash": "0x" + row_dict["transaction_hash"],
                    "safe_tx_hash": (
                        "0x" + row_dict["safe_tx_hash"]
                        if row_dict["safe_tx_hash"]
                        else None
                    ),
                    "method": row_dict["method"] if row_dict["method"] else None,
                    "contract_address": (
                        fast_to_checksum_address(row_dict["contract_address"])
                        if row_dict["contract_address"]
                        else None
                    ),
                }
                results.append(export_item)

        logger.debug(
            "[%s] Got %d export transactions from %d total using raw SQL",
            safe_address,
            len(results),
            total_count,
        )

        return results, total_count
