import datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from itertools import islice
from logging import getLogger
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypedDict,
    Union,
)

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.models import Case, Count, Index, JSONField, Max, Q, QuerySet
from django.db.models.expressions import F, OuterRef, RawSQL, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from model_utils.models import TimeStampedModel
from packaging.version import Version
from web3 import Web3
from web3.types import EventData

from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC
from gnosis.eth.django.models import (
    EthereumAddressV2Field,
    HexField,
    Keccak256Field,
    Uint256Field,
)
from gnosis.safe import SafeOperation
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.contracts.models import Contract

from .utils import clean_receipt_log

logger = getLogger(__name__)


class ConfirmationType(Enum):
    CONFIRMATION = 0
    EXECUTION = 1


class EthereumTxCallType(Enum):
    # https://ethereum.stackexchange.com/questions/63743/whats-the-difference-between-type-and-calltype-in-parity-trace
    CALL = 0
    DELEGATE_CALL = 1
    CALL_CODE = 2
    STATIC_CALL = 3

    @staticmethod
    def parse_call_type(call_type: Optional[str]):
        if not call_type:
            return None

        call_type = call_type.lower()
        if call_type == "call":
            return EthereumTxCallType.CALL
        elif call_type == "delegatecall":
            return EthereumTxCallType.DELEGATE_CALL
        elif call_type == "callcode":
            return EthereumTxCallType.CALL_CODE
        elif call_type == "staticcall":
            return EthereumTxCallType.STATIC_CALL
        else:
            return None


class InternalTxType(Enum):
    CALL = 0
    CREATE = 1
    SELF_DESTRUCT = 2
    REWARD = 3

    @staticmethod
    def parse(tx_type: str):
        tx_type = tx_type.upper()
        if tx_type == "CALL":
            return InternalTxType.CALL
        elif tx_type == "CREATE":
            return InternalTxType.CREATE
        elif tx_type in ("SUICIDE", "SELFDESTRUCT"):
            return InternalTxType.SELF_DESTRUCT
        elif tx_type == "REWARD":
            return InternalTxType.REWARD
        else:
            raise ValueError(f"{tx_type} is not a valid InternalTxType")


class TransferDict(TypedDict):
    block_number: int
    transaction_hash: HexBytes
    to: str
    _from: str
    _value: int
    execution_date: datetime.datetime
    _token_id: int
    token_address: str


class BulkCreateSignalMixin:
    def bulk_create(
        self, objs, batch_size: Optional[int] = None, ignore_conflicts: bool = False
    ):
        objs = list(objs)  # If not it won't be iterate later
        result = super().bulk_create(
            objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts
        )
        for obj in objs:
            post_save.send(obj.__class__, instance=obj, created=True)
        return result

    def bulk_create_from_generator(
        self, objs: Iterable[Any], batch_size: int = 100, ignore_conflicts: bool = False
    ) -> int:
        """
        Implementation in Django is not ok, as it will do `objs = list(objs)`. If objects come from a generator
        they will be brought to RAM. This approach is more friendly
        :return: Count of inserted elements
        """
        assert batch_size is not None and batch_size > 0
        total = 0
        while True:
            if inserted := len(
                self.bulk_create(
                    islice(objs, batch_size), ignore_conflicts=ignore_conflicts
                )
            ):
                total += inserted
            else:
                return total


class EthereumBlockManager(models.Manager):
    def get_or_create_from_block(self, block: Dict[str, Any], confirmed: bool = False):
        try:
            return self.get(block_hash=block["hash"])
        except self.model.DoesNotExist:
            return self.create_from_block(block, confirmed=confirmed)

    def create_from_block(
        self, block: Dict[str, Any], confirmed: bool = False
    ) -> "EthereumBlock":
        """
        :param block: Block Dict returned by Web3
        :param confirmed: If True we will not check for reorgs in the future
        :return: EthereumBlock model
        """
        try:
            with transaction.atomic():  # Needed for handling IntegrityError
                return super().create(
                    number=block["number"],
                    gas_limit=block["gasLimit"],
                    gas_used=block["gasUsed"],
                    timestamp=datetime.datetime.fromtimestamp(
                        block["timestamp"], datetime.timezone.utc
                    ),
                    block_hash=block["hash"].hex(),
                    parent_hash=block["parentHash"].hex(),
                    confirmed=confirmed,
                )
        except IntegrityError:
            db_block = self.get(number=block["number"])
            if HexBytes(db_block.block_hash) == block["hash"]:  # pragma: no cover
                # Block was inserted by another task
                return db_block
            else:
                # There's a wrong block with the same number
                db_block.confirmed = False  # Will be taken care of by the reorg task
                db_block.save(update_fields=["confirmed"])
                raise IntegrityError(
                    f"Error inserting block with hash={block['hash'].hex()}, "
                    f"there is a block with the same number={block['number']} inserted. "
                    f"Marking block as not confirmed"
                )

    @lru_cache(maxsize=10000)
    def get_timestamp_by_hash(self, block_hash: HexBytes) -> datetime.datetime:
        try:
            return self.values("timestamp").get(block_hash=block_hash)["timestamp"]
        except self.model.DoesNotExist:
            logger.error(
                "Block with hash=%s does not exist on database", block_hash.hex()
            )
            raise


class EthereumBlockQuerySet(models.QuerySet):
    def oldest_than(self, seconds: int):
        """
        :param seconds: Seconds
        :return: Blocks oldest than second, ordered by timestamp descending
        """
        return self.filter(
            timestamp__lte=timezone.now() - datetime.timedelta(seconds=seconds)
        ).order_by("-timestamp")

    def not_confirmed(self, to_block_number: Optional[int] = None):
        """
        :param to_block_number:
        :return: Block not confirmed until ``to_block_number``, if provided
        """
        queryset = self.filter(confirmed=False)
        if to_block_number is not None:
            queryset = queryset.filter(number__lte=to_block_number)
        return queryset


class EthereumBlock(models.Model):
    objects = EthereumBlockManager.from_queryset(EthereumBlockQuerySet)()
    number = models.PositiveIntegerField(primary_key=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Keccak256Field(unique=True)
    parent_hash = Keccak256Field(unique=True)
    # For reorgs, True if `current_block_number` - `number` >= MIN_CONFIRMATIONS
    confirmed = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"Block number={self.number} on {self.timestamp}"

    def _set_confirmed(self, confirmed: bool):
        if self.confirmed != confirmed:
            self.confirmed = confirmed
            self.save(update_fields=["confirmed"])

    def set_confirmed(self):
        return self._set_confirmed(True)

    def set_not_confirmed(self):
        return self._set_confirmed(False)


class EthereumTxManager(models.Manager):
    def create_from_tx_dict(
        self,
        tx: Dict[str, Any],
        tx_receipt: Optional[Dict[str, Any]] = None,
        ethereum_block: Optional[EthereumBlock] = None,
    ) -> "EthereumTx":
        data = HexBytes(tx.get("data") or tx.get("input"))
        # Supporting EIP1559
        if "gasPrice" in tx:
            gas_price = tx["gasPrice"]
        else:
            assert tx_receipt, f"Tx-receipt is required for EIP1559 tx {tx}"
            gas_price = tx_receipt.get("effectiveGasPrice")
            assert gas_price is not None, f"Gas price for tx {tx} cannot be None"
            gas_price = int(gas_price, 0)
        return super().create(
            block=ethereum_block,
            tx_hash=HexBytes(tx["hash"]).hex(),
            _from=tx["from"],
            gas=tx["gas"],
            gas_price=gas_price,
            gas_used=tx_receipt and tx_receipt["gasUsed"],
            logs=tx_receipt
            and [clean_receipt_log(log) for log in tx_receipt.get("logs", [])],
            status=tx_receipt and tx_receipt.get("status"),
            transaction_index=tx_receipt and tx_receipt["transactionIndex"],
            data=data if data else None,
            nonce=tx["nonce"],
            to=tx.get("to"),
            value=tx["value"],
        )


class EthereumTx(TimeStampedModel):
    objects = EthereumTxManager()
    block = models.ForeignKey(
        EthereumBlock,
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="txs",
    )  # If mined
    tx_hash = Keccak256Field(primary_key=True)
    gas_used = Uint256Field(null=True, default=None)  # If mined
    status = models.IntegerField(
        null=True, default=None, db_index=True
    )  # If mined. Old txs don't have `status`
    logs = ArrayField(JSONField(), null=True, default=None)  # If mined
    transaction_index = models.PositiveIntegerField(null=True, default=None)  # If mined
    _from = EthereumAddressV2Field(null=True, db_index=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    data = models.BinaryField(null=True)
    nonce = Uint256Field()
    to = EthereumAddressV2Field(null=True, db_index=True)
    value = Uint256Field()

    def __str__(self):
        return "{} status={} from={} to={}".format(
            self.tx_hash, self.status, self._from, self.to
        )

    @property
    def execution_date(self) -> Optional[datetime.datetime]:
        if self.block_id is not None:
            return self.block.timestamp
        return None

    @property
    def success(self) -> Optional[bool]:
        if self.status is not None:
            return self.status == 1

    def update_with_block_and_receipt(
        self, ethereum_block: "EthereumBlock", tx_receipt: Dict[str, Any]
    ):
        if self.block is None:
            self.block = ethereum_block
            self.gas_used = tx_receipt["gasUsed"]
            self.logs = [clean_receipt_log(log) for log in tx_receipt.get("logs", [])]
            self.status = tx_receipt.get("status")
            self.transaction_index = tx_receipt["transactionIndex"]
            return self.save(
                update_fields=[
                    "block",
                    "gas_used",
                    "logs",
                    "status",
                    "transaction_index",
                ]
            )


class TokenTransferQuerySet(models.QuerySet):
    def token_address(self, address: ChecksumAddress):
        """
        :param address:
        :return: Results filtered by token_address
        """
        return self.filter(address=address)

    def to_or_from(self, address: ChecksumAddress):
        """
        :param address:
        :return: Transfers with to or from equal to the provided `address`
        """
        return self.filter(Q(to=address) | Q(_from=address))

    def incoming(self, address: ChecksumAddress):
        return self.filter(to=address)

    def outgoing(self, address: ChecksumAddress):
        return self.filter(_from=address)

    def token_txs(self):
        raise NotImplementedError


class TokenTransferManager(BulkCreateSignalMixin, models.Manager):
    def tokens_used_by_address(self, address: ChecksumAddress) -> Set[ChecksumAddress]:
        return set(
            self.to_or_from(address).values_list("address", flat=True).distinct()
        )


class TokenTransfer(models.Model):
    objects = TokenTransferManager.from_queryset(TokenTransferQuerySet)()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(db_index=True)
    block_number = models.PositiveIntegerField()
    address = EthereumAddressV2Field()  # Token address
    _from = EthereumAddressV2Field()
    to = EthereumAddressV2Field()
    log_index = models.PositiveIntegerField()

    class Meta:
        abstract = True
        indexes = [
            Index(fields=["address"]),
            Index(fields=["_from", "timestamp"]),
            Index(fields=["to", "timestamp"]),
        ]
        unique_together = (("ethereum_tx", "log_index"),)

    def __str__(self):
        return f"Token Transfer from={self._from} to={self.to}"

    @staticmethod
    def _prepare_parameters_from_decoded_event(event_data: EventData) -> Dict[str, Any]:
        topic = HexBytes(event_data["topics"][0])
        expected_topic = HexBytes(ERC20_721_TRANSFER_TOPIC)
        if topic != expected_topic:
            raise ValueError(
                f"Not supported EventData, topic {topic.hex()} does not match expected {expected_topic.hex()}"
            )

        try:
            timestamp = EthereumBlock.objects.get_timestamp_by_hash(
                event_data["blockHash"]
            )
            return {
                "timestamp": timestamp,
                "block_number": event_data["blockNumber"],
                "ethereum_tx_id": event_data["transactionHash"],
                "log_index": event_data["logIndex"],
                "address": event_data["address"],
                "_from": event_data["args"]["from"],
                "to": event_data["args"]["to"],
            }
        except EthereumBlock.DoesNotExist:
            # Block is not found and should be present on DB. Reorg
            EthereumTx.objects.get(
                event_data["transactionHash"]
            ).block.set_not_confirmed()
            raise

    @classmethod
    def from_decoded_event(cls, event_data: EventData):
        raise NotImplementedError

    @property
    def created(self):
        return self.timestamp


class ERC20TransferQuerySet(TokenTransferQuerySet):
    def token_txs(self):
        return self.annotate(
            _value=F("value"),
            transaction_hash=F("ethereum_tx_id"),
            block=F("block_number"),
            execution_date=F("timestamp"),
            _token_id=RawSQL("NULL::numeric", ()),
            token_address=F("address"),
        )


class ERC20Transfer(TokenTransfer):
    objects = TokenTransferManager.from_queryset(ERC20TransferQuerySet)()
    value = Uint256Field()

    class Meta(TokenTransfer.Meta):
        abstract = False
        verbose_name = "ERC20 Transfer"
        verbose_name_plural = "ERC20 Transfers"
        unique_together = (("ethereum_tx", "log_index"),)

    def __str__(self):
        return f"ERC20 Transfer from={self._from} to={self.to} value={self.value}"

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> Union["ERC20Transfer"]:
        """
        Does not create the model, as it requires that `ethereum_tx` exists

        :param event_data:
        :return: `ERC20Transfer`
        :raises: ValueError
        """

        parameters = cls._prepare_parameters_from_decoded_event(event_data)

        if "value" in event_data["args"]:
            parameters["value"] = event_data["args"]["value"]
            return ERC20Transfer(**parameters)
        else:
            raise ValueError(
                f"Not supported EventData, `value` not present {event_data}"
            )

    def to_erc721_transfer(self):
        return ERC721Transfer(
            timestamp=self.timestamp,
            block_number=self.block_number,
            ethereum_tx=self.ethereum_tx,
            address=self.address,
            _from=self._from,
            to=self.to,
            log_index=self.log_index,
            token_id=self.value,
        )


class ERC721TransferManager(TokenTransferManager):
    # TODO Optimize this
    def erc721_owned_by(self, address: str) -> List[Tuple[str, int]]:
        """
        Returns erc721 owned by address, removing the ones sent

        :return: List of tuples(token_address: str, token_id: int)
        """
        # Get all the token history
        erc721_events = self.to_or_from(address)
        # Get tokens received and remove tokens transferred
        tokens_in: Tuple[str, int] = []
        tokens_out: Tuple[str, int] = []
        for erc721_event in erc721_events:
            token_address = erc721_event.address
            token_id = erc721_event.token_id
            if token_id is None:
                logger.error(
                    "TokenId for ERC721 info token=%s with owner=%s can never be None",
                    token_address,
                    address,
                )
                continue
            if erc721_event.to == erc721_event._from:
                continue  # Nice try ¯\_(ツ)_/¯

            if erc721_event.to == address:
                list_to_append = tokens_in
            else:
                list_to_append = tokens_out
            list_to_append.append((token_address, token_id))

        for token_out in tokens_out:  # Remove tokens sent from list
            if token_out in tokens_in:
                tokens_in.remove(token_out)
        return tokens_in


class ERC721TransferQuerySet(TokenTransferQuerySet):
    def token_txs(self):
        return self.annotate(
            _value=RawSQL("NULL::numeric", ()),
            transaction_hash=F("ethereum_tx_id"),
            block=F("block_number"),
            execution_date=F("timestamp"),
            _token_id=F("token_id"),
            token_address=F("address"),
        )


class ERC721Transfer(TokenTransfer):
    objects = ERC721TransferManager.from_queryset(ERC721TransferQuerySet)()
    token_id = Uint256Field()

    class Meta(TokenTransfer.Meta):
        abstract = False
        verbose_name = "ERC721 Transfer"
        verbose_name_plural = "ERC721 Transfers"
        unique_together = (("ethereum_tx", "log_index"),)

    def __str__(self):
        return (
            f"ERC721 Transfer from={self._from} to={self.to} token_id={self.token_id}"
        )

    @classmethod
    def from_decoded_event(cls, event_data: EventData) -> Union["ERC721Transfer"]:
        """
        Does not create the model, as it requires that `ethereum_tx` exists

        :param event_data:
        :return: `ERC721Transfer`
        :raises: ValueError
        """

        parameters = cls._prepare_parameters_from_decoded_event(event_data)

        if "tokenId" in event_data["args"]:
            parameters["token_id"] = event_data["args"]["tokenId"]
            return ERC721Transfer(**parameters)
        else:
            raise ValueError(
                f"Not supported EventData, `tokenId` not present {event_data}"
            )

    @property
    def value(self) -> Decimal:
        """
        Behave as a ERC20Transfer so it's easier to handle
        """
        return self.token_id

    def to_erc20_transfer(self):
        return ERC20Transfer(
            timestamp=self.timestamp,
            block_number=self.block_number,
            ethereum_tx=self.ethereum_tx,
            address=self.address,
            _from=self._from,
            to=self.to,
            log_index=self.log_index,
            value=self.token_id,
        )


class InternalTxManager(BulkCreateSignalMixin, models.Manager):
    def _trace_address_to_str(self, trace_address: Sequence[int]) -> str:
        return ",".join([str(address) for address in trace_address])

    def build_from_trace(
        self, trace: Dict[str, Any], ethereum_tx: EthereumTx
    ) -> "InternalTx":
        """
        Build a InternalTx object from trace, but it doesn't insert it on database
        :param trace:
        :param ethereum_tx:
        :return: InternalTx not inserted
        """
        data = trace["action"].get("input") or trace["action"].get("init")
        tx_type = InternalTxType.parse(trace["type"])
        call_type = EthereumTxCallType.parse_call_type(trace["action"].get("callType"))
        trace_address_str = self._trace_address_to_str(trace["traceAddress"])
        return InternalTx(
            ethereum_tx=ethereum_tx,
            timestamp=ethereum_tx.block.timestamp,
            block_number=ethereum_tx.block_id,
            trace_address=trace_address_str,
            _from=trace["action"].get("from"),
            gas=trace["action"].get("gas", 0),
            data=data if data else None,
            to=trace["action"].get("to") or trace["action"].get("address"),
            value=trace["action"].get("value") or trace["action"].get("balance", 0),
            gas_used=(trace.get("result") or {}).get("gasUsed", 0),
            contract_address=(trace.get("result") or {}).get("address"),
            code=(trace.get("result") or {}).get("code"),
            output=(trace.get("result") or {}).get("output"),
            refund_address=trace["action"].get("refundAddress"),
            tx_type=tx_type.value,
            call_type=call_type.value if call_type else None,
            error=trace.get("error"),
        )

    def get_or_create_from_trace(
        self, trace: Dict[str, Any], ethereum_tx: EthereumTx
    ) -> Tuple["InternalTx", bool]:
        tx_type = InternalTxType.parse(trace["type"])
        call_type = EthereumTxCallType.parse_call_type(trace["action"].get("callType"))
        trace_address_str = self._trace_address_to_str(trace["traceAddress"])
        return self.get_or_create(
            ethereum_tx=ethereum_tx,
            trace_address=trace_address_str,
            defaults={
                "timestamp": ethereum_tx.block.timestamp,
                "block_number": ethereum_tx.block_id,
                "_from": trace["action"].get("from"),
                "gas": trace["action"].get("gas", 0),
                "data": trace["action"].get("input") or trace["action"].get("init"),
                "to": trace["action"].get("to") or trace["action"].get("address"),
                "value": trace["action"].get("value")
                or trace["action"].get("balance", 0),
                "gas_used": (trace.get("result") or {}).get("gasUsed", 0),
                "contract_address": (trace.get("result") or {}).get("address"),
                "code": (trace.get("result") or {}).get("code"),
                "output": (trace.get("result") or {}).get("output"),
                "refund_address": trace["action"].get("refundAddress"),
                "tx_type": tx_type.value,
                "call_type": call_type.value if call_type else None,
                "error": trace.get("error"),
            },
        )


class InternalTxQuerySet(models.QuerySet):
    def ether_txs(self):
        return self.filter(
            call_type=EthereumTxCallType.CALL.value, value__gt=0
        ).annotate(
            _value=F("value"),
            transaction_hash=F("ethereum_tx_id"),
            block=F("block_number"),
            execution_date=F("timestamp"),
            _token_id=RawSQL("NULL::numeric", ()),
            token_address=Value(None, output_field=EthereumAddressV2Field()),
        )

    def ether_txs_for_address(self, address: str):
        return self.ether_txs().filter(Q(to=address) | Q(_from=address))

    def ether_incoming_txs_for_address(self, address: str):
        return self.ether_txs().filter(to=address)

    def token_txs(self):
        values = [
            "block",
            "transaction_hash",
            "to",
            "_from",
            "_value",
            "execution_date",
            "_token_id",
            "token_address",
        ]
        erc20_queryset = ERC20Transfer.objects.token_txs()
        erc721_queryset = ERC721Transfer.objects.token_txs()
        return (
            erc20_queryset.values(*values)
            .union(erc721_queryset.values(*values), all=True)
            .order_by("-block")
        )

    def token_incoming_txs_for_address(self, address: str):
        values = [
            "block",
            "transaction_hash",
            "to",
            "_from",
            "_value",
            "execution_date",
            "_token_id",
            "token_address",
        ]
        erc20_queryset = ERC20Transfer.objects.incoming(address).token_txs()
        erc721_queryset = ERC721Transfer.objects.incoming(address).token_txs()
        return (
            erc20_queryset.values(*values)
            .union(erc721_queryset.values(*values), all=True)
            .order_by("-block")
        )

    def ether_and_token_txs(self, address: str):
        erc20_queryset = ERC20Transfer.objects.to_or_from(address).token_txs()
        erc721_queryset = ERC721Transfer.objects.to_or_from(address).token_txs()
        ether_queryset = self.ether_txs_for_address(address)
        return self.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )

    def ether_and_token_incoming_txs(self, address: str):
        erc20_queryset = ERC20Transfer.objects.incoming(address).token_txs()
        erc721_queryset = ERC721Transfer.objects.incoming(address).token_txs()
        ether_queryset = self.ether_incoming_txs_for_address(address)
        return self.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )

    def union_ether_and_token_txs(
        self,
        erc20_queryset: QuerySet,
        erc721_queryset: QuerySet,
        ether_queryset: QuerySet,
    ) -> TransferDict:
        values = [
            "block",
            "transaction_hash",
            "to",
            "_from",
            "_value",
            "execution_date",
            "_token_id",
            "token_address",
        ]
        return (
            ether_queryset.values(*values)
            .union(erc20_queryset.values(*values), all=True)
            .union(erc721_queryset.values(*values), all=True)
            .order_by("-block")
        )

    def can_be_decoded(self):
        """
        Every InternalTx can be decoded if:
            - Has data
            - InternalTx is not errored
            - EthereumTx is successful (not reverted or out of gas)
            - CallType is a DELEGATE_CALL (to the master copy contract)
            - Not already decoded
        :return: Txs that can be decoded
        """
        return self.exclude(data=None).filter(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error=None,
            ethereum_tx__status=1,
            decoded_tx=None,
        )


class InternalTx(models.Model):
    objects = InternalTxManager.from_queryset(InternalTxQuerySet)()
    ethereum_tx = models.ForeignKey(
        EthereumTx, on_delete=models.CASCADE, related_name="internal_txs"
    )
    timestamp = models.DateTimeField(db_index=True)
    block_number = models.PositiveIntegerField()
    _from = EthereumAddressV2Field(null=True)  # For SELF-DESTRUCT it can be null
    gas = Uint256Field()
    data = models.BinaryField(null=True)  # `input` for Call, `init` for Create
    to = EthereumAddressV2Field(null=True)
    value = Uint256Field()
    gas_used = Uint256Field()
    contract_address = EthereumAddressV2Field(null=True, db_index=True)  # Create
    code = models.BinaryField(null=True)  # Create
    output = models.BinaryField(null=True)  # Call
    refund_address = EthereumAddressV2Field(
        null=True, db_index=True
    )  # For SELF-DESTRUCT
    tx_type = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in InternalTxType], db_index=True
    )
    call_type = models.PositiveSmallIntegerField(
        null=True,
        choices=[(tag.value, tag.name) for tag in EthereumTxCallType],
        db_index=True,
    )  # Call
    trace_address = models.CharField(max_length=600)  # Stringified traceAddress
    error = models.CharField(max_length=200, null=True)

    class Meta:
        unique_together = (("ethereum_tx", "trace_address"),)
        indexes = [
            models.Index(
                name="history_internaltx_value_idx",
                fields=["value"],
                condition=Q(value__gt=0),
            ),
            Index(fields=["_from", "timestamp"]),
            Index(fields=["to", "timestamp"]),
        ]

    def __str__(self):
        if self.to:
            return "Internal tx hash={} from={} to={}".format(
                HexBytes(self.ethereum_tx_id).hex(), self._from, self.to
            )
        else:
            return "Internal tx hash={} from={}".format(
                HexBytes(self.ethereum_tx_id).hex(), self._from
            )

    @property
    def created(self):
        return self.timestamp

    @property
    def can_be_decoded(self) -> bool:
        return bool(
            self.is_delegate_call
            and not self.error
            and self.data
            and self.ethereum_tx.success
        )

    @property
    def is_call(self):
        return InternalTxType(self.tx_type) == InternalTxType.CALL

    @property
    def is_create(self):
        return InternalTxType(self.tx_type) == InternalTxType.CREATE

    @property
    def is_decoded(self):
        try:
            return bool(self.decoded_tx)
        except InternalTxDecoded.DoesNotExist:
            return False

    @property
    def is_delegate_call(self) -> bool:
        if self.call_type is None:
            return False
        else:
            return (
                EthereumTxCallType(self.call_type) == EthereumTxCallType.DELEGATE_CALL
            )

    @property
    def is_ether_transfer(self) -> bool:
        return self.call_type == EthereumTxCallType.CALL.value and self.value > 0

    @property
    def is_relevant(self):
        return self.can_be_decoded or self.is_ether_transfer or self.contract_address

    @property
    def trace_address_as_list(self) -> List[int]:
        if not self.trace_address:
            return []
        else:
            return [int(x) for x in self.trace_address.split(",")]

    def get_parent(self) -> Optional["InternalTx"]:
        if (
            "," not in self.trace_address
        ):  # We are expecting something like 0,0,1 or 1,1
            return None
        parent_trace_address = ",".join(self.trace_address.split(",")[:-1])
        try:
            return InternalTx.objects.filter(
                ethereum_tx_id=self.ethereum_tx_id, trace_address=parent_trace_address
            ).get()
        except InternalTx.DoesNotExist:
            return None

    def get_child(self, index: int) -> Optional["InternalTx"]:
        child_trace_address = f"{self.trace_address},{index}"
        try:
            return InternalTx.objects.filter(
                ethereum_tx_id=self.ethereum_tx_id, trace_address=child_trace_address
            ).get()
        except InternalTx.DoesNotExist:
            return None


class InternalTxDecodedManager(BulkCreateSignalMixin, models.Manager):
    pass


class InternalTxDecodedQuerySet(models.QuerySet):
    def for_safe(self, safe_address: str):
        """
        :param safe_address:
        :return: Queryset of all InternalTxDecoded for one Safe with `safe_address`
        """
        return self.filter(internal_tx___from=safe_address)

    def for_indexed_safes(self):
        """
        :return: Queryset of InternalTxDecoded for Safes already indexed or calling `setup`. Use this to index Safes
        for the first time
        """
        return self.filter(
            Q(
                internal_tx___from__in=SafeContract.objects.values("address")
            )  # Just Safes indexed
            | Q(function_name="setup")  # This way we can index new Safes without events
        )

    def not_processed(self):
        return self.filter(processed=False)

    def order_by_processing_queue(self):
        """
        :return: Transactions ordered to be processed. First `setup` and then older transactions
        """
        return self.annotate(
            is_setup=Case(
                When(function_name="setup", then=Value(0)),
                default=Value(1),
            )
        ).order_by(
            "is_setup",
            "internal_tx__block_number",
            "internal_tx__ethereum_tx__transaction_index",
            "internal_tx__trace_address",
        )

    def pending_for_safes(self):
        """
        :return: Pending `InternalTxDecoded` sorted by block number and then transaction index inside the block
        """
        return (
            self.not_processed()
            .for_indexed_safes()
            .select_related(
                "internal_tx__ethereum_tx__block",
            )
            .order_by_processing_queue()
        )

    def pending_for_safe(self, safe_address: str):
        """
        :return: Pending `InternalTxDecoded` sorted by block number and then transaction index inside the block
        """
        return self.pending_for_safes().filter(internal_tx___from=safe_address)

    def safes_pending_to_be_processed(self) -> QuerySet:
        """
        :return: List of Safe addresses that have transactions pending to be processed
        """
        return (
            self.not_processed()
            .for_indexed_safes()
            .values_list("internal_tx___from", flat=True)
            .distinct("internal_tx___from")
        )


class InternalTxDecoded(models.Model):
    objects = InternalTxDecodedManager.from_queryset(InternalTxDecodedQuerySet)()
    internal_tx = models.OneToOneField(
        InternalTx,
        on_delete=models.CASCADE,
        related_name="decoded_tx",
        primary_key=True,
    )
    function_name = models.CharField(max_length=256, db_index=True)
    arguments = JSONField()
    processed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                name="history_decoded_processed_idx",
                fields=["processed"],
                condition=Q(processed=False),
            )
        ]
        verbose_name_plural = "Internal txs decoded"

    def __str__(self):
        return (
            f'{"Processed" if self.processed else "Not Processed"} '
            f"fn-name={self.function_name} with arguments={self.arguments}"
        )

    @property
    def address(self) -> str:
        return self.internal_tx._from

    @property
    def block_number(self) -> Type[int]:
        return self.internal_tx.ethereum_tx.block_id

    @property
    def tx_hash(self) -> Type[int]:
        return self.internal_tx.ethereum_tx_id

    def set_processed(self):
        self.processed = True
        return self.save(update_fields=["processed"])


class MultisigTransactionManager(models.Manager):
    def last_nonce(self, safe: str) -> Optional[int]:
        """
        :param safe:
        :return: nonce of the last executed and mined transaction. It will be None if there's no transactions or none
        of them is mined
        """
        nonce_query = (
            self.filter(safe=safe)
            .exclude(ethereum_tx=None)
            .order_by("-nonce")
            .values("nonce")
            .first()
        )
        if nonce_query:
            return nonce_query["nonce"]

    def last_valid_transaction(self, safe: str) -> Optional["MultisigTransaction"]:
        """
        Find last transaction where signers match the owners registered for that Safe. Transactions out of sync
        have an invalid `safeNonce`, so `safeTxHash` is not valid and owners recovered from the signatures wouldn't be
        valid. We exclude `Approved hashes` and `Contract signatures` as that owners are not retrieved using the
        signature, so they will show the right owner even if `safeNonce` is not valid

        :param safe:
        :return: Last valid indexed transaction mined
        """
        # Build list of every owner known for that Safe (even if it was deleted/replaced). Changes of collision for
        # invalid recovered owners from signatures are almost impossible
        owners_set = set()
        for owners_list in (
            SafeStatus.objects.filter(address=safe)
            .values_list("owners", flat=True)
            .distinct()
        ):
            owners_set.update(owners_list)

        return (
            MultisigTransaction.objects.filter(
                safe=safe,
                confirmations__owner__in=owners_set,
                confirmations__signature_type__in=[
                    SafeSignatureType.EOA.value,
                    SafeSignatureType.ETH_SIGN.value,
                ],
            )
            .exclude(ethereum_tx=None)
            .order_by("-nonce")
            .first()
        )

    def safes_with_number_of_transactions_executed(self):
        return (
            self.executed()
            .values("safe")
            .annotate(transactions=Count("safe"))
            .order_by("-transactions")
        )

    def safes_with_number_of_transactions_executed_and_master_copy(self):
        master_copy_query = (
            SafeStatus.objects.filter(address=OuterRef("safe"))
            .order_by("-nonce")
            .values("master_copy")
        )

        return (
            self.safes_with_number_of_transactions_executed()
            .annotate(master_copy=Subquery(master_copy_query[:1]))
            .order_by("-transactions")
        )

    def not_indexed_metadata_contract_addresses(self):
        """
        Find contracts with metadata (abi, contract name) not indexed

        :return:
        """
        return (
            self.exclude(data=None)
            .exclude(to__in=Contract.objects.values("address"))
            .values_list("to", flat=True)
            .distinct()
        )


class MultisigTransactionQuerySet(models.QuerySet):
    def ether_transfers(self):
        return self.exclude(value=0)

    def executed(self):
        return self.exclude(ethereum_tx=None)

    def not_executed(self):
        return self.filter(ethereum_tx=None)

    def with_confirmations(self):
        return self.exclude(confirmations__isnull=True)

    def without_confirmations(self):
        return self.filter(confirmations__isnull=True)

    def with_confirmations_required(self):
        """
        Add confirmations required for execution when the tx was mined (threshold of the Safe at that point)
        :return: queryset with `confirmations_required: int` field
        """
        threshold_query = (
            SafeStatus.objects.filter(internal_tx__ethereum_tx=OuterRef("ethereum_tx"))
            .sorted_reverse_by_mined()
            .values("threshold")
        )

        return self.annotate(confirmations_required=Subquery(threshold_query[:1]))

    def queued(self, safe_address: str):
        """
        :return: Transactions not executed with safe-nonce greater than the last executed nonce. If no transaction is
        executed every transaction is returned
        """
        subquery = (
            self.executed()
            .filter(safe=safe_address)
            .values("safe")
            .annotate(max_nonce=Max("nonce"))
            .values("max_nonce")
        )
        return (
            self.not_executed()
            .annotate(
                max_executed_nonce=Coalesce(
                    Subquery(subquery), Value(-1), output_field=Uint256Field()
                )
            )
            .filter(nonce__gt=F("max_executed_nonce"), safe=safe_address)
        )


class MultisigTransaction(TimeStampedModel):
    objects = MultisigTransactionManager.from_queryset(MultisigTransactionQuerySet)()
    safe_tx_hash = Keccak256Field(primary_key=True)
    safe = EthereumAddressV2Field(db_index=True)
    ethereum_tx = models.ForeignKey(
        EthereumTx,
        null=True,
        default=None,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="multisig_txs",
    )
    to = EthereumAddressV2Field(null=True, db_index=True)
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeOperation]
    )
    safe_tx_gas = Uint256Field()
    base_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressV2Field(null=True)
    refund_receiver = EthereumAddressV2Field(null=True)
    signatures = models.BinaryField(null=True)  # When tx is executed
    nonce = Uint256Field(db_index=True)
    failed = models.BooleanField(null=True, default=None, db_index=True)
    origin = models.CharField(
        null=True, default=None, max_length=200
    )  # To store arbitrary data on the tx
    trusted = models.BooleanField(
        default=False, db_index=True
    )  # Txs proposed by a delegate or with one confirmation

    class Meta:
        permissions = [
            ("create_trusted", "Can create trusted transactions"),
        ]

    def __str__(self):
        return f"{self.safe} - {self.nonce} - {self.safe_tx_hash}"

    @property
    def execution_date(self) -> Optional[datetime.datetime]:
        if self.ethereum_tx_id and self.ethereum_tx.block_id is not None:
            return self.ethereum_tx.block.timestamp
        return None

    @property
    def executed(self) -> bool:
        return bool(self.ethereum_tx_id and (self.ethereum_tx.block_id is not None))

    @property
    def owners(self) -> Optional[List[str]]:
        if not self.signatures:
            return []
        else:
            signatures = bytes(self.signatures)
            safe_signatures = SafeSignature.parse_signature(
                signatures, self.safe_tx_hash
            )
            return [safe_signature.owner for safe_signature in safe_signatures]

    def data_should_be_decoded(self) -> bool:
        """
        Decoding could lead people to be tricked, and this is real critical when using DELEGATE_CALL as the operation

        :return: `True` if data should be decoded, `False` otherwise
        """
        return not (
            self.operation == SafeOperation.DELEGATE_CALL.value
            and self.to not in Contract.objects.trusted_addresses_for_delegate_call()
        )


class ModuleTransactionManager(models.Manager):
    def not_indexed_metadata_contract_addresses(self):
        """
        Find contracts with metadata (abi, contract name) not indexed
        :return:
        """
        return (
            self.exclude(module__in=Contract.objects.values("address"))
            .values_list("module", flat=True)
            .distinct()
        )


class ModuleTransaction(TimeStampedModel):
    objects = ModuleTransactionManager()
    internal_tx = models.OneToOneField(
        InternalTx, on_delete=models.CASCADE, related_name="module_tx", primary_key=True
    )
    safe = EthereumAddressV2Field(
        db_index=True
    )  # Just for convenience, it could be retrieved from `internal_tx`
    module = EthereumAddressV2Field(
        db_index=True
    )  # Just for convenience, it could be retrieved from `internal_tx`
    to = EthereumAddressV2Field(db_index=True)
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeOperation]
    )
    failed = models.BooleanField(default=False)

    def __str__(self):
        if self.value:
            return f"{self.safe} - {self.to} - {self.value}"
        else:
            return f"{self.safe} - {self.to} - 0x{bytes(self.data).hex()[:6]}"

    @property
    def execution_date(self) -> Optional[datetime.datetime]:
        if (
            self.internal_tx.ethereum_tx_id
            and self.internal_tx.ethereum_tx.block_id is not None
        ):
            return self.internal_tx.ethereum_tx.block.timestamp
        return None


class MultisigConfirmationManager(models.Manager):
    def remove_unused_confirmations(
        self, safe: str, current_safe_none: int, owner: str
    ) -> int:
        """
        :return: Remove confirmations for not executed transactions with nonce higher or equal than
        the current Safe nonce for a Safe and an owner (as an owner can be an owner of multiple Safes).
        Used when an owner is removed from the Safe.
        """
        return self.filter(
            multisig_transaction__ethereum_tx=None,  # Not executed
            multisig_transaction__safe=safe,
            multisig_transaction__nonce__gte=current_safe_none,
            owner=owner,
        ).delete()[0]


class MultisigConfirmationQuerySet(models.QuerySet):
    def without_transaction(self):
        return self.filter(multisig_transaction=None)

    def with_transaction(self):
        return self.exclude(multisig_transaction=None)


class MultisigConfirmation(TimeStampedModel):
    objects = MultisigConfirmationManager.from_queryset(MultisigConfirmationQuerySet)()
    ethereum_tx = models.ForeignKey(
        EthereumTx,
        on_delete=models.CASCADE,
        related_name="multisig_confirmations",
        null=True,
    )  # `null=True` for signature confirmations
    multisig_transaction = models.ForeignKey(
        MultisigTransaction,
        on_delete=models.CASCADE,
        null=True,
        related_name="confirmations",
    )
    multisig_transaction_hash = Keccak256Field(
        null=True, db_index=True
    )  # Use this while we don't have a `multisig_transaction`
    owner = EthereumAddressV2Field()

    signature = HexField(null=True, default=None, max_length=5000)
    signature_type = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeSignatureType], db_index=True
    )

    class Meta:
        unique_together = (("multisig_transaction_hash", "owner"),)
        ordering = ["created"]

    def __str__(self):
        if self.multisig_transaction_id:
            return f"Confirmation of owner={self.owner} for transaction-hash={self.multisig_transaction_hash}"
        else:
            return f"Confirmation of owner={self.owner} for existing transaction={self.multisig_transaction_hash}"


class MonitoredAddress(models.Model):
    address = EthereumAddressV2Field(primary_key=True)
    initial_block_number = models.IntegerField(
        default=0
    )  # Block number when address received first tx
    tx_block_number = models.IntegerField(
        null=True, default=None, db_index=True
    )  # Block number when last internal tx scan ended

    class Meta:
        abstract = True
        verbose_name_plural = "Monitored addresses"

    def __str__(self):
        return (
            f"Address={self.address} - Initial-block-number={self.initial_block_number}"
            f" - Tx-block-number={self.tx_block_number}"
        )


class ProxyFactory(MonitoredAddress):
    class Meta:
        verbose_name_plural = "Proxy factories"
        ordering = ["tx_block_number"]


def validate_version(value: str):
    try:
        if not value:
            raise ValueError("Empty version not allowed")
        Version(value)
    except ValueError as exc:
        raise ValidationError(
            _("%(value)s is not a valid version: %(reason)s"),
            params={"value": value, "reason": str(exc)},
        )


class SafeMasterCopyManager(models.Manager):
    def get_version_for_address(self, address: ChecksumAddress) -> Optional[str]:
        try:
            return self.filter(address=address).only("version").get().version
        except self.model.DoesNotExist:
            return None


class SafeMasterCopyQueryset(models.QuerySet):
    def l2(self):
        return self.filter(l2=True)

    def not_l2(self):
        return self.filter(l2=False)

    def relevant(self):
        """
        :return: Relevant master copies for this network. If network is `L2`, only `L2` master copies are returned.
            Otherwise, all master copies are returned
        """
        if settings.ETH_L2_NETWORK:
            return self.l2()
        else:
            return self.all()


class SafeMasterCopy(MonitoredAddress):
    objects = SafeMasterCopyManager.from_queryset(SafeMasterCopyQueryset)()
    version = models.CharField(max_length=20, validators=[validate_version])
    deployer = models.CharField(max_length=50, default="Gnosis")
    l2 = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Safe master copies"
        ordering = ["tx_block_number"]


class SafeContract(models.Model):
    address = EthereumAddressV2Field(primary_key=True)
    ethereum_tx = models.ForeignKey(
        EthereumTx, on_delete=models.CASCADE, related_name="safe_contracts"
    )
    erc20_block_number = models.IntegerField(
        default=0, db_index=True
    )  # Block number of last scan of erc20

    def __str__(self):
        return f"Safe address={self.address} - ethereum-tx={self.ethereum_tx_id}"

    @property
    def created(self):
        return self.ethereum_tx.block.timestamp

    @property
    def created_block_number(self) -> Optional[Type[int]]:
        if self.ethereum_tx:
            return self.ethereum_tx.block_id


class SafeContractDelegateManager(models.Manager):
    def get_delegates_for_safe(self, address: ChecksumAddress) -> Set[ChecksumAddress]:
        return set(
            self.filter(safe_contract_id=address)
            .values_list("delegate", flat=True)
            .distinct()
        )

    def get_delegates_for_safe_and_owners(
        self, safe_address: ChecksumAddress, owner_addresses: Sequence[ChecksumAddress]
    ) -> Set[ChecksumAddress]:
        if not owner_addresses:
            return set()
        return set(
            self.filter(
                # If safe_contract is null on SafeContractDelegate, delegates are valid for every Safe
                Q(safe_contract_id=safe_address)
                | Q(safe_contract=None)
            )
            .filter(delegator__in=owner_addresses)
            .values_list("delegate", flat=True)
            .distinct()
        )


class SafeContractDelegate(models.Model):
    """
    The owners of the Safe can add users so they can propose/retrieve txs as if they were the owners of the Safe
    """

    objects = SafeContractDelegateManager()
    safe_contract = models.ForeignKey(
        SafeContract,
        on_delete=models.CASCADE,
        related_name="safe_contract_delegates",
        null=True,
        default=None,
    )
    delegate = EthereumAddressV2Field()
    delegator = EthereumAddressV2Field()  # Owner who created the delegate
    label = models.CharField(max_length=50)
    read = models.BooleanField(default=True)  # For permissions in the future
    write = models.BooleanField(default=True)

    class Meta:
        unique_together = (("safe_contract", "delegate", "delegator"),)

    def __str__(self):
        return (
            f"Delegator={self.delegator} Delegate={self.delegate} for Safe={self.safe_contract_id} - "
            f"Label={self.label}"
        )


class SafeStatusManager(models.Manager):
    pass


class SafeStatusQuerySet(models.QuerySet):
    def sorted_by_mined(self):
        """
        Last SafeStatus first. Usually ordering by `nonce` it should be enough, but in some cases
        (MultiSend, calling functions inside the Safe like adding/removing owners...) there could be multiple
        transactions with the same nonce. `address` must be part of the expression to use `distinct()` later

        :return: SafeStatus QuerySet sorted
        """
        return self.order_by(
            "address",
            "-nonce",
            "-internal_tx__block_number",
            "-internal_tx__ethereum_tx__transaction_index",
            "-internal_tx__trace_address",
        )

    def sorted_reverse_by_mined(self):
        return self.order_by(
            "address",
            "nonce",
            "internal_tx__block_number",
            "internal_tx__ethereum_tx__transaction_index",
            "internal_tx__trace_address",
        )

    def addresses_for_owner(self, owner_address: str) -> Set[str]:
        """
        Use raw query to get the Safes for an owner. We order by the internal_tx_id instead of using JOIN to get
        the internal tx index as a shortcut. It's not as accurate but should be enough

        :param owner_address:
        :return:
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                    SELECT DISTINCT(address)
                    FROM (
                        SELECT address, owners,
                                rank() OVER (PARTITION BY address ORDER BY nonce DESC, internal_tx_id DESC) AS pos
                        FROM history_safestatus
                        WHERE address IN (
                            SELECT address FROM history_safestatus
                            WHERE owners @> ARRAY[%s]::bytea[]
                        )
                        ) AS ss
                    WHERE pos = 1 AND owners @> ARRAY[%s]::bytea[];
                """,
                [HexBytes(owner_address), HexBytes(owner_address)],
            )
            return {Web3.toChecksumAddress(row[0].hex()) for row in cursor.fetchall()}

    def last_for_every_address(self) -> QuerySet:
        return (
            self.distinct("address")  # Uses PostgreSQL `DISTINCT ON`
            .select_related("internal_tx__ethereum_tx")
            .sorted_by_mined()
        )

    def last_for_address(self, address: str) -> Optional["SafeStatus"]:
        return self.filter(address=address).sorted_by_mined().first()


class SafeStatus(models.Model):
    objects = SafeStatusManager.from_queryset(SafeStatusQuerySet)()
    internal_tx = models.OneToOneField(
        InternalTx,
        on_delete=models.CASCADE,
        related_name="safe_status",
        primary_key=True,
    )
    address = EthereumAddressV2Field(db_index=True)
    owners = ArrayField(EthereumAddressV2Field())
    threshold = Uint256Field()
    nonce = Uint256Field(default=0)
    master_copy = EthereumAddressV2Field()
    fallback_handler = EthereumAddressV2Field()
    guard = EthereumAddressV2Field(default=None, null=True)
    enabled_modules = ArrayField(EthereumAddressV2Field(), default=list)

    class Meta:
        indexes = [
            Index(fields=["address", "-nonce"]),  # Index on address and nonce DESC
            Index(fields=["address", "-nonce", "-internal_tx"]),  # For Window search
            GinIndex(fields=["owners"]),
        ]
        unique_together = (("internal_tx", "address"),)
        verbose_name_plural = "Safe statuses"

    def __str__(self):
        return f"safe={self.address} threshold={self.threshold} owners={self.owners} nonce={self.nonce}"

    @property
    def block_number(self) -> int:
        return self.internal_tx.ethereum_tx.block_id

    def is_corrupted(self) -> bool:
        """
        SafeStatus nonce must be incremental. If current nonce is bigger than the number of SafeStatus for that Safe
        something is wrong. There could be more SafeStatus than nonce (e.g. a call to a MultiSend
        adding owners and enabling a Module in the same contract `execTransaction`)

        :return: `True` if corrupted, `False` otherwise
        """
        return (
            self.__class__.objects.distinct("nonce")
            .filter(address=self.address, nonce__lte=self.nonce)
            .count()
            <= self.nonce
        )

    def previous(self) -> Optional["SafeStatus"]:
        """
        :return: SafeStatus with the previous nonce
        """
        return (
            self.__class__.objects.filter(address=self.address, nonce__lt=self.nonce)
            .sorted_by_mined()
            .first()
        )

    def store_new(self, internal_tx: InternalTx) -> None:
        self.internal_tx = internal_tx
        return self.save(force_insert=True)


class WebHookType(Enum):
    NEW_CONFIRMATION = 0
    PENDING_MULTISIG_TRANSACTION = 1
    EXECUTED_MULTISIG_TRANSACTION = 2
    INCOMING_ETHER = 3
    INCOMING_TOKEN = 4
    CONFIRMATION_REQUEST = 5
    SAFE_CREATED = 6
    MODULE_TRANSACTION = 7
    OUTGOING_ETHER = 8
    OUTGOING_TOKEN = 9


class WebHookQuerySet(models.QuerySet):
    def matching_for_address(self, address: str):
        return self.filter(Q(address=address) | Q(address=None))


class WebHook(models.Model):
    objects = WebHookQuerySet.as_manager()
    address = EthereumAddressV2Field(db_index=True, null=True, blank=True)
    url = models.URLField()
    authorization = models.CharField(
        max_length=500,
        null=True,
        default=None,
        help_text="Set HTTP Authorization header with the value",
    )
    # Configurable webhook types to listen to
    new_confirmation = models.BooleanField(default=True)
    pending_outgoing_transaction = models.BooleanField(default=True)
    new_executed_outgoing_transaction = models.BooleanField(default=True)
    new_incoming_transaction = models.BooleanField(default=True)
    new_safe = models.BooleanField(default=True)
    new_module_transaction = models.BooleanField(default=True)
    new_outgoing_transaction = models.BooleanField(default=True)

    class Meta:
        unique_together = (("address", "url"),)

    def __str__(self):
        if self.address:
            return f"Webhook for safe={self.address} to url={self.url}"
        else:
            return f"Webhook to every address to url={self.url}"

    def is_valid_for_webhook_type(self, webhook_type: WebHookType):
        if webhook_type == WebHookType.NEW_CONFIRMATION and not self.new_confirmation:
            return False
        elif (
            webhook_type == WebHookType.PENDING_MULTISIG_TRANSACTION
            and not self.pending_outgoing_transaction
        ):
            return False
        elif (
            webhook_type == WebHookType.EXECUTED_MULTISIG_TRANSACTION
            and not self.new_executed_outgoing_transaction
        ):
            return False
        elif (
            webhook_type in (WebHookType.INCOMING_TOKEN, WebHookType.INCOMING_ETHER)
            and not self.new_incoming_transaction
        ):
            return False
        elif webhook_type == WebHookType.SAFE_CREATED and not self.new_safe:
            return False
        elif (
            webhook_type == WebHookType.MODULE_TRANSACTION
            and not self.new_module_transaction
        ):
            return False
        elif (
            webhook_type in (WebHookType.OUTGOING_TOKEN, WebHookType.OUTGOING_ETHER)
            and not self.new_outgoing_transaction
        ):
            return False
        else:
            return True
