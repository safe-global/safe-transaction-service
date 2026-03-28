import logging
import pickle
import zlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

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
from safe_eth.safe import SafeOperationEnum

from safe_transaction_service.contracts.tx_decoder import get_tx_decoder
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

    def _get_native_transfers_from_multisend(
        self,
        multisig_tx: MultisigTransaction,
    ) -> list[TransferDict]:
        """
        Build synthetic ETHER_TRANSFER entries from decoded multiSend data.
        Used when the chain does not index internal txs (e.g. Berachain, Scroll, Unichain),
        so native transfers in batch txs would otherwise be missing from the API.
        """
        if not multisig_tx.data or not multisig_tx.ethereum_tx_id:
            return []
        if multisig_tx.operation != SafeOperationEnum.DELEGATE_CALL.value:
            return []
        ethereum_tx = multisig_tx.ethereum_tx
        if not ethereum_tx or not getattr(ethereum_tx, "block", None):
            return []
        try:
            decoded = get_tx_decoder().decode_multisend_data(multisig_tx.data)
        except Exception:
            return []
        if not decoded:
            return []
        safe_address = multisig_tx.safe
        if isinstance(safe_address, bytes):
            safe_address = fast_to_checksum_address(safe_address)
        block = ethereum_tx.block
        execution_date = block.timestamp
        block_number = block.number
        tx_hash = multisig_tx.ethereum_tx_id
        if isinstance(tx_hash, bytes):
            pass
        else:
            tx_hash = HexBytes(tx_hash) if tx_hash else None
        if not tx_hash:
            return []
        result: list[TransferDict] = []
        for idx, item in enumerate(decoded):
            operation = item.get("operation")
            value_str = item.get("value")
            to_addr = item.get("to")
            if operation != 0:
                continue
            try:
                value_int = int(value_str) if value_str else 0
            except (TypeError, ValueError):
                continue
            if value_int <= 0 or not to_addr:
                continue
            to_checksum = (
                fast_to_checksum_address(to_addr)
                if isinstance(to_addr, bytes)
                else to_addr
            )
            result.append(
                {
                    "block": block_number,
                    "transaction_hash": tx_hash,
                    "to": to_checksum,
                    "_from": safe_address,
                    "_value": value_int,
                    "execution_date": execution_date,
                    "_token_id": None,
                    "token_address": None,
                    "_log_index": None,
                    "_trace_address": str(idx),
                }
            )
        return result

    def _enrich_transfers_from_multisend_decoded(
        self,
        safe_address: str,
        ids_with_multisig_txs: dict,
        transfer_dict: defaultdict,
    ) -> defaultdict:
        """
        For multiSend txs that have no indexed native transfers (e.g. chains without
        tracing), add synthetic ETHER_TRANSFER entries from decoded batch data.
        """
        for _tx_id, multisig_txs in ids_with_multisig_txs.items():
            for multisig_tx in multisig_txs:
                if multisig_tx.ethereum_tx_id is None:
                    continue
                tx_id = multisig_tx.ethereum_tx_id
                existing = transfer_dict.get(tx_id, [])
                ether_count = sum(1 for t in existing if t.get("token_address") is None)
                if ether_count > 0:
                    continue
                synthetic = self._get_native_transfers_from_multisend(multisig_tx)
                if not synthetic:
                    continue
                for t in synthetic:
                    t["token"] = None
                transfer_dict[tx_id].extend(synthetic)
        return transfer_dict

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
                strict=False,
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

        # Enrich with native transfers from decoded multiSend when tracing didn't index them
        # (e.g. on Berachain, Scroll, Unichain where internal txs may not be available)
        transfer_dict = self._enrich_transfers_from_multisend_decoded(
            safe_address,
            ids_with_multisig_txs,
            transfer_dict,
        )

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

            result: MultisigTransaction | ModuleTransaction | EthereumTx | None
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
        execution_date_gte: datetime | None = None,
        execution_date_lte: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
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

        # Build timestamp conditions for each subquery
        erc20_timestamp_conditions = ""
        erc721_timestamp_conditions = ""
        native_timestamp_conditions = ""

        if execution_date_gte:
            assert type(execution_date_gte) is datetime
            erc20_timestamp_conditions += (
                f" AND erc20.timestamp >= '{execution_date_gte}'"
            )
            erc721_timestamp_conditions += (
                f" AND erc721.timestamp >= '{execution_date_gte}'"
            )
            native_timestamp_conditions += (
                f" AND itx.timestamp >= '{execution_date_gte}'"
            )

        if execution_date_lte:
            assert type(execution_date_lte) is datetime
            erc20_timestamp_conditions += (
                f" AND erc20.timestamp <= '{execution_date_lte}'"
            )
            erc721_timestamp_conditions += (
                f" AND erc721.timestamp <= '{execution_date_lte}'"
            )
            native_timestamp_conditions += (
                f" AND itx.timestamp <= '{execution_date_lte}'"
            )

        # Main query that unions all transaction types with their transfers
        main_query = f"""
        WITH export_data AS (
            -- ERC20 Transfers
            SELECT
                encode(%s, 'hex') as safe_address,
                encode(COALESCE(erc20._from, modtx.module), 'hex') as from_address,
                encode(COALESCE(erc20.to, modtx.to), 'hex') as to_address,
                erc20.value::text as amount,
                'erc20' as asset_type,
                encode(erc20.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(COALESCE(et._from, modtx.module), 'hex') as executor_address,
                erc20.timestamp as execution_date,
                erc20.timestamp as executed_at,
                COALESCE(mt.origin->> 'note', '') as note,
                encode(erc20.ethereum_tx_id, 'hex') as transaction_hash,
                encode(COALESCE(mt.to, modtx.to), 'hex') as contract_address,
                -- Just get the nonces from the provided Safe
                CASE WHEN mt.safe = %s THEN mt.nonce ELSE NULL END AS nonce,
                -- Assigns a row number to each ERC20 transfer grouped by tx and log index.
                -- Prioritizes module > multisig > standalone using execution time as tiebreaker.
                ROW_NUMBER() OVER (
                    PARTITION BY erc20.ethereum_tx_id, erc20.log_index
                    ORDER BY
                        CASE
                            WHEN modtx.internal_tx_id IS NOT NULL THEN 1
                        WHEN mt.safe IS NOT NULL THEN 2
                        ELSE 3
                        END,
                    COALESCE(mt.created, erc20.timestamp)
                ) AS rn
            FROM history_erc20transfer erc20
            JOIN history_saferelevanttransaction rel ON rel.safe = %s AND rel.ethereum_tx_id = erc20.ethereum_tx_id
            JOIN history_ethereumtx et ON rel.ethereum_tx_id = et.tx_hash
            LEFT JOIN history_multisigtransaction mt ON erc20.ethereum_tx_id = mt.ethereum_tx_id
            LEFT JOIN history_internaltx itx ON itx.ethereum_tx_id = erc20.ethereum_tx_id
            LEFT JOIN history_moduletransaction modtx ON modtx.internal_tx_id = itx.id
            LEFT JOIN tokens_token t ON erc20.address = t.address
            WHERE (erc20.to = %s OR erc20._from = %s){erc20_timestamp_conditions}

            UNION ALL
            -- ERC721 Transfers
            SELECT
                encode(%s, 'hex') as safe_address,
                encode(COALESCE(erc721._from, modtx.module), 'hex') as from_address,
                encode(COALESCE(erc721.to, modtx.to), 'hex') as to_address,
                '1' as amount,
                'erc721' as asset_type,
                encode(erc721.address, 'hex') as asset_address,
                t.symbol as asset_symbol,
                t.decimals as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(COALESCE(et._from, modtx.module), 'hex') as executor_address,
                erc721.timestamp as execution_date,
                erc721.timestamp as executed_at,
                COALESCE(mt.origin->> 'note', '') as note,
                encode(erc721.ethereum_tx_id, 'hex') as transaction_hash,
                encode(COALESCE(modtx.to, mt.to), 'hex') as contract_address,
                -- Just get the nonces from the provided Safe
                CASE WHEN mt.safe = %s THEN mt.nonce ELSE NULL END AS nonce,
                -- Assigns a row number to each ERC721 transfer grouped by tx and log index.
                -- Prioritizes module > multisig > standalone using execution time as tiebreaker.
                ROW_NUMBER() OVER (
                    PARTITION BY erc721.ethereum_tx_id, erc721.log_index
                    ORDER BY
                        CASE
                            WHEN modtx.internal_tx_id IS NOT NULL THEN 1
                            WHEN mt.safe IS NOT NULL  THEN 2
                        ELSE 3
                        END,
                    COALESCE(mt.created, erc721.timestamp)
                ) AS rn
            FROM history_erc721transfer erc721
            JOIN history_saferelevanttransaction rel ON rel.safe = %s AND rel.ethereum_tx_id = erc721.ethereum_tx_id
            JOIN history_ethereumtx et ON rel.ethereum_tx_id = et.tx_hash
            LEFT JOIN history_multisigtransaction mt ON erc721.ethereum_tx_id = mt.ethereum_tx_id
            LEFT JOIN history_internaltx itx ON itx.ethereum_tx_id = erc721.ethereum_tx_id
            LEFT JOIN history_moduletransaction modtx ON modtx.internal_tx_id = itx.id
            LEFT JOIN tokens_token t ON erc721.address = t.address
            WHERE (erc721.to = %s OR erc721._from = %s){erc721_timestamp_conditions}

            UNION ALL

            --Native transfers
            SELECT
                encode(%s, 'hex') as safe_address,
                encode(itx._from, 'hex') as from_address,
                encode(itx.to, 'hex') as to_address,
                itx.value::text as amount,
                'native' as asset_type,
                null as asset_address,
                'ETH' as asset_symbol,
                18 as asset_decimals,
                encode(mt.proposer, 'hex') as proposer_address,
                mt.created as proposed_at,
                encode(COALESCE(et._from, modtx.module), 'hex') as executor_address,
                itx.timestamp as execution_date,
                itx.timestamp as executed_at,
                COALESCE(mt.origin->> 'note', '') as note,
                encode(itx.ethereum_tx_id, 'hex') as transaction_hash,
                encode(COALESCE(mt.to, modtx.to), 'hex') as contract_address,
                -- Just get the nonces from the provided Safe
                CASE WHEN mt.safe = %s THEN mt.nonce ELSE NULL END AS nonce,
                -- Assigns a row number to each native transfer grouped by tx and log index.
                -- Prioritizes module > multisig > standalone using execution time as tiebreaker.
                ROW_NUMBER() OVER (
                    PARTITION BY itx.ethereum_tx_id, itx.trace_address
                    ORDER BY
                        CASE
                            WHEN modtx.internal_tx_id IS NOT NULL THEN 1
                            WHEN mt.safe is NOT NULL THEN 2
                            ELSE 3
                        END,
                    COALESCE(mt.created, itx.timestamp)
                ) AS rn
            FROM history_internaltx itx
            JOIN history_saferelevanttransaction rel ON rel.safe = %s AND rel.ethereum_tx_id = itx.ethereum_tx_id
            JOIN history_ethereumtx et ON rel.ethereum_tx_id = et.tx_hash
            LEFT JOIN history_multisigtransaction mt ON itx.ethereum_tx_id = mt.ethereum_tx_id
            LEFT JOIN history_moduletransaction modtx ON modtx.internal_tx_id = itx.id
            WHERE(itx.to = %s OR itx._from = %s)
            AND itx.call_type = 0
            AND itx.value > 0{native_timestamp_conditions}
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
            contract_address,
            nonce
        FROM export_data
        WHERE rn = 1
        ORDER BY execution_date DESC, transaction_hash
        LIMIT %s OFFSET %s
        """
        # Parameters for main query (safe_address repeated for each UNION)
        safe_address_bytes = HexBytes(safe_address)
        main_params = [
            safe_address_bytes
        ] * 15 + [  # 15 instances of safe address in the query
            limit,
            offset,
        ]

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
            ether_transfers.count() + erc20_transfers.count() + erc721_transfers.count()
        )
        with connection.cursor() as cursor:
            # Get the data
            cursor.execute(main_query, main_params)
            columns = [col[0] for col in cursor.description]
            results = []

            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row, strict=False))

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
                    "contract_address": (
                        fast_to_checksum_address(row_dict["contract_address"])
                        if row_dict["contract_address"]
                        else None
                    ),
                    "nonce": row_dict["nonce"],
                }
                results.append(export_item)

        logger.debug(
            "[%s] Got %d export transactions from %d total using raw SQL",
            safe_address,
            len(results),
            total_count,
        )

        return results, total_count
