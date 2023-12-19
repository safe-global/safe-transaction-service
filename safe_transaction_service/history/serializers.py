import json
from enum import Enum
from typing import Any, Dict, List, Optional

from drf_yasg.utils import swagger_serializer_method
from eth_typing import ChecksumAddress, HexStr
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.django.models import EthereumAddressV2Field as EthereumAddressDbField
from gnosis.eth.django.models import Keccak256Field as Keccak256DbField
from gnosis.eth.django.serializers import (
    EthereumAddressField,
    HexadecimalField,
    Sha3HashField,
)
from gnosis.safe import Safe
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType
from gnosis.safe.serializers import SafeMultisigTxSerializerV1

from safe_transaction_service.contracts.tx_decoder import (
    TxDecoderException,
    get_db_tx_decoder,
)
from safe_transaction_service.tokens.serializers import TokenInfoResponseSerializer
from safe_transaction_service.utils.serializers import get_safe_owners

from .exceptions import NodeConnectionException
from .helpers import DelegateSignatureHelper
from .models import (
    EthereumTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    TransferDict,
)
from .services.safe_service import SafeCreationInfo


def get_data_decoded_from_data(data: bytes, address: Optional[ChecksumAddress] = None):
    tx_decoder = get_db_tx_decoder()
    try:
        return tx_decoder.get_data_decoded(data, address=address)
    except TxDecoderException:
        return None


class GnosisBaseModelSerializer(serializers.ModelSerializer):
    serializer_field_mapping = (
        serializers.ModelSerializer.serializer_field_mapping.copy()
    )
    serializer_field_mapping[EthereumAddressDbField] = serializers.CharField
    serializer_field_mapping[Keccak256DbField] = serializers.CharField


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeMultisigConfirmationSerializer(serializers.Serializer):
    signature = HexadecimalField(min_length=65)  # Signatures must be at least 65 bytes

    def validate_signature(self, signature: bytes):
        safe_tx_hash = self.context["safe_tx_hash"]
        try:
            multisig_transaction: MultisigTransaction = (
                MultisigTransaction.objects.select_related("ethereum_tx").get(
                    safe_tx_hash=safe_tx_hash
                )
            )
        except MultisigTransaction.DoesNotExist as exc:
            raise NotFound(
                f"Multisig transaction with safe-tx-hash={safe_tx_hash} was not found"
            ) from exc

        if multisig_transaction.executed:
            raise ValidationError(
                f"Transaction with safe-tx-hash={safe_tx_hash} was already executed"
            )

        safe_address = multisig_transaction.safe
        ethereum_client = EthereumClientProvider()
        safe = Safe(safe_address, ethereum_client)
        safe_tx = safe.build_multisig_tx(
            multisig_transaction.to,
            multisig_transaction.value,
            multisig_transaction.data,
            multisig_transaction.operation,
            multisig_transaction.safe_tx_gas,
            multisig_transaction.base_gas,
            multisig_transaction.gas_price,
            multisig_transaction.gas_token,
            multisig_transaction.refund_receiver,
            safe_nonce=multisig_transaction.nonce,
        )

        safe_owners = get_safe_owners(safe_address)
        parsed_signatures = SafeSignature.parse_signature(
            signature, safe_tx_hash, safe_tx.safe_tx_hash_preimage
        )
        signature_owners = []
        ethereum_client = EthereumClientProvider()
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if owner not in safe_owners:
                raise ValidationError(
                    f"Signer={owner} is not an owner. Current owners={safe_owners}"
                )
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={owner} is not valid"
                )
            if owner in signature_owners:
                raise ValidationError(f"Signature for owner={owner} is duplicated")

            signature_owners.append(owner)
        return signature

    def save(self, **kwargs):
        safe_tx_hash = self.context["safe_tx_hash"]
        signature = self.validated_data["signature"]
        multisig_confirmations = []
        parsed_signatures = SafeSignature.parse_signature(signature, safe_tx_hash)
        for safe_signature in parsed_signatures:
            multisig_confirmation, _ = MultisigConfirmation.objects.get_or_create(
                multisig_transaction_hash=safe_tx_hash,
                owner=safe_signature.owner,
                defaults={
                    "multisig_transaction_id": safe_tx_hash,
                    "signature": safe_signature.export_signature(),
                    "signature_type": safe_signature.signature_type.value,
                },
            )
            multisig_confirmations.append(multisig_confirmation)

        if self.validated_data["signature"]:
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).update(
                trusted=True
            )
        return multisig_confirmations


class SafeMultisigTransactionSerializer(SafeMultisigTxSerializerV1):
    contract_transaction_hash = Sha3HashField()
    sender = EthereumAddressField()
    # TODO Make signature mandatory
    signature = HexadecimalField(
        allow_null=True, required=False, min_length=65
    )  # Signatures must be at least 65 bytes
    origin = serializers.CharField(max_length=200, allow_null=True, default=None)

    def validate_origin(self, origin):
        # Origin field on db is a JsonField
        if origin:
            try:
                origin = json.loads(origin)
            except ValueError:
                pass
        else:
            origin = {}

        return origin

    def validate(self, attrs):
        super().validate(attrs)

        ethereum_client = EthereumClientProvider()
        safe_address = attrs["safe"]

        safe = Safe(safe_address, ethereum_client)
        safe_tx = safe.build_multisig_tx(
            attrs["to"],
            attrs["value"],
            attrs["data"],
            attrs["operation"],
            attrs["safe_tx_gas"],
            attrs["base_gas"],
            attrs["gas_price"],
            attrs["gas_token"],
            attrs["refund_receiver"],
            safe_nonce=attrs["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash

        # Check safe tx hash matches
        if safe_tx_hash != attrs["contract_transaction_hash"]:
            raise ValidationError(
                f"Contract-transaction-hash={safe_tx_hash.hex()} "
                f'does not match provided contract-tx-hash={attrs["contract_transaction_hash"].hex()}'
            )

        # Check there's not duplicated tx with same `nonce` or same `safeTxHash` for the same Safe.
        # We allow duplicated if existing tx is not executed
        multisig_transactions = MultisigTransaction.objects.filter(
            safe=safe_address, nonce=attrs["nonce"]
        ).executed()
        if multisig_transactions:
            for multisig_transaction in multisig_transactions:
                if multisig_transaction.safe_tx_hash == safe_tx_hash.hex():
                    raise ValidationError(
                        f"Tx with safe-tx-hash={safe_tx_hash.hex()} "
                        f"for safe={safe_address} was already executed in "
                        f"tx-hash={multisig_transaction.ethereum_tx_id}"
                    )

            raise ValidationError(
                f"Tx with nonce={safe_tx.safe_nonce} for safe={safe_address} "
                f"already executed in tx-hash={multisig_transactions[0].ethereum_tx_id}"
            )

        safe_owners = get_safe_owners(safe_address)
        attrs["safe_owners"] = safe_owners

        delegates = SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
            safe_address, safe_owners
        )
        allowed_senders = set(safe_owners) | delegates
        if not attrs["sender"] in allowed_senders:
            raise ValidationError(
                f'Sender={attrs["sender"]} is not an owner or delegate. '
                f"Current owners={safe_owners}. Delegates={delegates}"
            )

        signature_owners = []
        # TODO Make signature mandatory
        signature = attrs.get("signature", b"")
        parsed_signatures = SafeSignature.parse_signature(
            signature, safe_tx_hash, safe_hash_preimage=safe_tx.safe_tx_hash_preimage
        )
        attrs["parsed_signatures"] = parsed_signatures
        # If there's at least one signature, transaction is trusted (until signatures are mandatory)
        attrs["trusted"] = bool(parsed_signatures)
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={owner} is not valid"
                )

            if owner in delegates and len(parsed_signatures) > 1:
                raise ValidationError(
                    "Just one signature is expected if using delegates"
                )
            if owner not in allowed_senders:
                raise ValidationError(
                    f"Signer={owner} is not an owner or delegate. "
                    f"Current owners={safe_owners}. Delegates={delegates}"
                )
            if owner in signature_owners:
                raise ValidationError(f"Signature for owner={owner} is duplicated")

            signature_owners.append(owner)

        # TODO Make signature mandatory. len(signature_owners) must be >= 1
        if signature_owners and attrs["sender"] not in signature_owners:
            raise ValidationError(
                f'Signature does not match sender={attrs["sender"]}. '
                f"Calculated owners={signature_owners}"
            )

        return attrs

    def save(self, **kwargs):
        safe_tx_hash = self.validated_data["contract_transaction_hash"]
        origin = self.validated_data["origin"]
        trusted = self.validated_data["trusted"]
        if not trusted:
            # Check user permission
            if (
                self.context
                and (request := self.context.get("request"))
                and (user := request.user)
            ):
                trusted = user.has_perm("history.create_trusted")

        if self.validated_data["sender"] in self.validated_data["safe_owners"]:
            proposer = self.validated_data["sender"]
        else:
            proposer = (
                SafeContractDelegate.objects.get_for_safe_and_delegate(
                    self.validated_data["safe"],
                    self.validated_data["safe_owners"],
                    self.validated_data["sender"],
                )
                .first()
                .delegator
            )

        multisig_transaction, created = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=safe_tx_hash,
            defaults={
                "safe": self.validated_data["safe"],
                "to": self.validated_data["to"],
                "value": self.validated_data["value"],
                "data": self.validated_data["data"]
                if self.validated_data["data"]
                else None,
                "operation": self.validated_data["operation"],
                "safe_tx_gas": self.validated_data["safe_tx_gas"],
                "base_gas": self.validated_data["base_gas"],
                "gas_price": self.validated_data["gas_price"],
                "gas_token": self.validated_data["gas_token"],
                "refund_receiver": self.validated_data["refund_receiver"],
                "nonce": self.validated_data["nonce"],
                "origin": origin,
                "trusted": trusted,
                "proposer": proposer,
            },
        )

        if not created and trusted and not multisig_transaction.trusted:
            multisig_transaction.origin = origin
            multisig_transaction.trusted = trusted
            multisig_transaction.save(update_fields=["origin", "trusted"])

        for safe_signature in self.validated_data.get("parsed_signatures"):
            if safe_signature.owner in self.validated_data["safe_owners"]:
                MultisigConfirmation.objects.get_or_create(
                    multisig_transaction_hash=safe_tx_hash,
                    owner=safe_signature.owner,
                    defaults={
                        "multisig_transaction": multisig_transaction,
                        "signature": safe_signature.export_signature(),
                        "signature_type": safe_signature.signature_type.value,
                    },
                )
        return multisig_transaction


class SafeMultisigTransactionEstimateSerializer(serializers.Serializer):
    to = EthereumAddressField()
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True, allow_blank=True)
    operation = serializers.IntegerField(min_value=0)

    def save(self, **kwargs):
        safe_address = self.context["safe_address"]
        ethereum_client = EthereumClientProvider()
        safe = Safe(safe_address, ethereum_client)
        exc = None
        # Retry thrice to get an estimation
        for _ in range(3):
            try:
                safe_tx_gas = safe.estimate_tx_gas(
                    self.validated_data["to"],
                    self.validated_data["value"],
                    self.validated_data["data"],
                    self.validated_data["operation"],
                )
                return {"safe_tx_gas": safe_tx_gas}
            except (IOError, ValueError) as _exc:
                exc = _exc
        raise NodeConnectionException(
            f"Node connection error when estimating gas for Safe {safe_address}"
        ) from exc


class DelegateSignatureCheckerMixin:
    """
    Mixin to include delegate signature validation
    """

    def check_delegate_signature(
        self,
        ethereum_client: EthereumClient,
        signature: bytes,
        operation_hash: bytes,
        delegator: ChecksumAddress,
    ) -> bool:
        """
        Checks signature and returns a valid owner if found, None otherwise

        :param ethereum_client:
        :param signature:
        :param operation_hash:
        :param delegator:
        :return: `True` if signature is valid for the delegator, `False` otherwise
        """
        safe_signatures = SafeSignature.parse_signature(signature, operation_hash)
        if not safe_signatures:
            raise ValidationError("Signature is not valid")

        if len(safe_signatures) > 1:
            raise ValidationError(
                "More than one signatures detected, just one is expected"
            )

        safe_signature = safe_signatures[0]
        owner = safe_signature.owner
        if owner == delegator:
            if not safe_signature.is_valid(ethereum_client, owner):
                raise ValidationError(
                    f"Signature of type={safe_signature.signature_type.name} "
                    f"for delegator={delegator} is not valid"
                )
            return True
        return False


class DelegateSerializer(DelegateSignatureCheckerMixin, serializers.Serializer):
    safe = EthereumAddressField(allow_null=True, required=False, default=None)
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65)
    label = serializers.CharField(max_length=50)

    def validate(self, attrs):
        super().validate(attrs)

        safe_address: Optional[ChecksumAddress] = attrs.get("safe")
        if (
            safe_address
            and not SafeContract.objects.filter(address=safe_address).exists()
        ):
            raise ValidationError(
                f"Safe={safe_address} does not exist or it's still not indexed"
            )

        signature = attrs["signature"]
        delegate = attrs["delegate"]  # Delegate address to be added/removed
        delegator = attrs[
            "delegator"
        ]  # Delegator giving permissions to delegate (signer)

        ethereum_client = EthereumClientProvider()
        if safe_address:
            # Valid delegators must be owners
            valid_delegators = get_safe_owners(safe_address)
            if delegator not in valid_delegators:
                raise ValidationError(
                    f"Provided delegator={delegator} is not an owner of Safe={safe_address}"
                )

        # Tries to find a valid delegator using multiple strategies
        for operation_hash in DelegateSignatureHelper.calculate_all_possible_hashes(
            delegate
        ):
            if self.check_delegate_signature(
                ethereum_client, signature, operation_hash, delegator
            ):
                return attrs

        raise ValidationError(
            f"Signature does not match provided delegator={delegator}"
        )

    def save(self, **kwargs):
        safe_address = self.validated_data["safe"]
        delegate = self.validated_data["delegate"]
        delegator = self.validated_data["delegator"]
        label = self.validated_data["label"]
        obj, _ = SafeContractDelegate.objects.update_or_create(
            safe_contract_id=safe_address,
            delegate=delegate,
            delegator=delegator,
            defaults={
                "label": label,
            },
        )
        return obj


class DelegateDeleteSerializer(DelegateSignatureCheckerMixin, serializers.Serializer):
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65)

    def validate(self, attrs):
        super().validate(attrs)

        signature = attrs["signature"]
        delegate = attrs["delegate"]  # Delegate address to be added/removed
        delegator = attrs["delegator"]  # Delegator

        ethereum_client = EthereumClientProvider()
        # Tries to find a valid delegator using multiple strategies
        for operation_hash in DelegateSignatureHelper.calculate_all_possible_hashes(
            delegate
        ):
            for signer in (delegate, delegator):
                if self.check_delegate_signature(
                    ethereum_client, signature, operation_hash, signer
                ):
                    return attrs

        raise ValidationError(
            f"Signature does not match provided delegate={delegate} or delegator={delegator}"
        )


class DataDecoderSerializer(serializers.Serializer):
    data = HexadecimalField(allow_null=False, allow_blank=False, min_length=4)
    to = EthereumAddressField(allow_null=True, required=False)


# ================================================ #
#            Response Serializers
# ================================================ #
class SafeModuleTransactionResponseSerializer(GnosisBaseModelSerializer):
    execution_date = serializers.DateTimeField()
    data = HexadecimalField(allow_null=True, allow_blank=True)
    data_decoded = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField()
    block_number = serializers.SerializerMethodField()
    is_successful = serializers.SerializerMethodField()
    module_transaction_id = serializers.SerializerMethodField(
        help_text="Internally calculated parameter to uniquely identify a moduleTransaction \n"
        "`ModuleTransactionId = i+tx_hash+trace_address`"
    )

    class Meta:
        model = ModuleTransaction
        fields = (
            "created",
            "execution_date",
            "block_number",
            "is_successful",
            "transaction_hash",
            "safe",
            "module",
            "to",
            "value",
            "data",
            "operation",
            "data_decoded",
            "module_transaction_id",
        )

    def get_block_number(self, obj: ModuleTransaction) -> Optional[int]:
        return obj.internal_tx.block_number

    def get_data_decoded(self, obj: ModuleTransaction) -> Dict[str, Any]:
        return get_data_decoded_from_data(
            obj.data.tobytes() if obj.data else b"", address=obj.to
        )

    def get_is_successful(self, obj: ModuleTransaction) -> bool:
        return not obj.failed

    def get_transaction_hash(self, obj: ModuleTransaction) -> HexStr:
        return obj.internal_tx.ethereum_tx_id

    def get_module_transaction_id(self, obj: ModuleTransaction) -> str:
        return "i" + obj.internal_tx.ethereum_tx_id[2:] + obj.internal_tx.trace_address


class SafeMultisigConfirmationResponseSerializer(GnosisBaseModelSerializer):
    submission_date = serializers.DateTimeField(source="created")
    transaction_hash = serializers.SerializerMethodField()
    signature = HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    class Meta:
        model = MultisigConfirmation
        fields = (
            "owner",
            "submission_date",
            "transaction_hash",
            "signature",
            "signature_type",
        )

    def get_transaction_hash(self, obj: MultisigConfirmation) -> str:
        return obj.ethereum_tx_id

    def get_signature_type(self, obj: MultisigConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeMultisigTransactionResponseSerializer(SafeMultisigTxSerializerV1):
    execution_date = serializers.DateTimeField()
    submission_date = serializers.DateTimeField(
        source="created"
    )  # First seen by this service
    modified = serializers.DateTimeField()
    block_number = serializers.SerializerMethodField()
    transaction_hash = Sha3HashField(source="ethereum_tx_id")
    safe_tx_hash = Sha3HashField()
    proposer = EthereumAddressField()
    executor = serializers.SerializerMethodField()
    value = serializers.CharField()
    is_executed = serializers.BooleanField(source="executed")
    is_successful = serializers.SerializerMethodField()
    gas_price = serializers.CharField()
    eth_gas_price = serializers.SerializerMethodField()
    max_fee_per_gas = serializers.SerializerMethodField()
    max_priority_fee_per_gas = serializers.SerializerMethodField()
    gas_used = serializers.SerializerMethodField()
    fee = serializers.SerializerMethodField()
    origin = serializers.SerializerMethodField()
    data_decoded = serializers.SerializerMethodField()
    confirmations_required = serializers.IntegerField()
    confirmations = serializers.SerializerMethodField()
    trusted = serializers.BooleanField()
    signatures = HexadecimalField(allow_null=True, required=False)

    def get_block_number(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx_id:
            return obj.ethereum_tx.block_id

    @swagger_serializer_method(
        serializer_or_field=SafeMultisigConfirmationResponseSerializer
    )
    def get_confirmations(self, obj: MultisigTransaction) -> Dict[str, Any]:
        """
        Filters confirmations queryset
        :param obj: MultisigConfirmation instance
        :return: Serialized queryset
        """
        return SafeMultisigConfirmationResponseSerializer(
            obj.confirmations, many=True
        ).data

    def get_executor(self, obj: MultisigTransaction) -> Optional[str]:
        if obj.ethereum_tx_id:
            return obj.ethereum_tx._from

    def get_fee(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx:
            if obj.ethereum_tx.gas_used and obj.ethereum_tx.gas_price:
                return str(obj.ethereum_tx.gas_used * obj.ethereum_tx.gas_price)

    def get_eth_gas_price(self, obj: MultisigTransaction) -> Optional[str]:
        if obj.ethereum_tx and obj.ethereum_tx.gas_price:
            return str(obj.ethereum_tx.gas_price)

    def get_max_fee_per_gas(self, obj: MultisigTransaction) -> Optional[str]:
        if obj.ethereum_tx and obj.ethereum_tx.max_fee_per_gas:
            return str(obj.ethereum_tx.max_fee_per_gas)

    def get_max_priority_fee_per_gas(self, obj: MultisigTransaction) -> Optional[str]:
        if obj.ethereum_tx and obj.ethereum_tx.max_priority_fee_per_gas:
            return str(obj.ethereum_tx.max_priority_fee_per_gas)

    def get_gas_used(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx and obj.ethereum_tx.gas_used:
            return obj.ethereum_tx.gas_used

    def get_is_successful(self, obj: MultisigTransaction) -> Optional[bool]:
        return None if obj.failed is None else not obj.failed

    def get_origin(self, obj: MultisigTransaction) -> str:
        return obj.origin if isinstance(obj.origin, str) else json.dumps(obj.origin)

    def get_data_decoded(self, obj: MultisigTransaction) -> Dict[str, Any]:
        # If delegate call contract must be whitelisted (security)
        if obj.data_should_be_decoded():
            return get_data_decoded_from_data(
                obj.data.tobytes() if obj.data else b"", address=obj.to
            )


class IndexingStatusSerializer(serializers.Serializer):
    current_block_number = serializers.IntegerField()
    erc20_block_number = serializers.IntegerField()
    erc20_synced = serializers.BooleanField()
    master_copies_block_number = serializers.IntegerField()
    master_copies_synced = serializers.BooleanField()
    synced = serializers.BooleanField()


class ERC20IndexingStatusSerializer(serializers.Serializer):
    current_block_number = serializers.IntegerField()
    erc20_block_number = serializers.IntegerField()
    erc20_synced = serializers.BooleanField()


class Erc20InfoSerializer(serializers.Serializer):
    name = serializers.CharField()
    symbol = serializers.CharField()
    decimals = serializers.IntegerField()
    logo_uri = serializers.CharField()


class SafeBalanceResponseSerializer(serializers.Serializer):
    token_address = serializers.CharField()
    token = Erc20InfoSerializer()
    balance = serializers.CharField()


class SafeBalanceUsdResponseSerializer(SafeBalanceResponseSerializer):
    eth_value = serializers.CharField()
    timestamp = serializers.DateTimeField()
    fiat_balance = serializers.CharField()
    fiat_conversion = serializers.CharField()
    fiat_code = serializers.CharField()


class SafeCollectibleResponseSerializer(serializers.Serializer):
    address = serializers.CharField()
    token_name = serializers.CharField()
    token_symbol = serializers.CharField()
    logo_uri = serializers.CharField()
    id = serializers.CharField()
    uri = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    image_uri = serializers.CharField()
    metadata = serializers.DictField()


class SafeMultisigTransactionEstimateResponseSerializer(serializers.Serializer):
    safe_tx_gas = serializers.CharField()


class SafeDelegateResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField(source="safe_contract_id")
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    label = serializers.CharField(max_length=50)


class SafeCreationInfoResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    creator = EthereumAddressField()
    transaction_hash = Sha3HashField()
    factory_address = EthereumAddressField()
    master_copy = EthereumAddressField(allow_null=True)
    setup_data = HexadecimalField(allow_null=True)
    data_decoded = serializers.SerializerMethodField()

    def get_data_decoded(self, obj: SafeCreationInfo) -> Dict[str, Any]:
        return get_data_decoded_from_data(obj.setup_data or b"")


class SafeInfoResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    nonce = serializers.IntegerField()
    threshold = serializers.IntegerField()
    owners = serializers.ListField(child=EthereumAddressField())
    master_copy = EthereumAddressField()
    modules = serializers.ListField(child=EthereumAddressField())
    fallback_handler = EthereumAddressField()
    guard = EthereumAddressField()
    version = serializers.CharField(allow_null=True)


class MasterCopyResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    version = serializers.CharField()
    deployer = serializers.CharField()
    deployed_block_number = serializers.IntegerField(source="initial_block_number")
    last_indexed_block_number = serializers.IntegerField(source="tx_block_number")
    l2 = serializers.BooleanField()


class ModulesResponseSerializer(serializers.Serializer):
    safes = serializers.ListField(child=EthereumAddressField())


class OwnerResponseSerializer(serializers.Serializer):
    safes = serializers.ListField(child=EthereumAddressField())


class TransferType(Enum):
    ETHER_TRANSFER = 0
    ERC20_TRANSFER = 1
    ERC721_TRANSFER = 2
    UNKNOWN = 3


class TransferResponseSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    execution_date = serializers.DateTimeField()
    block_number = serializers.IntegerField(source="block")
    transaction_hash = Sha3HashField()
    to = EthereumAddressField()
    from_ = EthereumAddressField(source="_from", allow_zero_address=True)
    value = serializers.CharField(allow_null=True, source="_value")
    token_id = serializers.CharField(allow_null=True, source="_token_id")
    token_address = EthereumAddressField(allow_null=True, default=None)
    transfer_id = serializers.SerializerMethodField(
        help_text="Internally calculated parameter to uniquely identify a transfer \n"
        "Token transfers are calculated as `transferId = e+tx_hash+log_index` \n"
        "Ether transfers are calculated as `transferId = i+tx_hash+trace_address`"
    )

    def get_fields(self):
        result = super().get_fields()
        # Rename `from_` to `from`
        from_ = result.pop("from_")
        result["from"] = from_
        return result

    def get_type(self, obj: TransferDict) -> str:
        if obj["token_address"] is None:
            return TransferType.ETHER_TRANSFER.name
        else:
            if obj["_value"] is not None:
                return TransferType.ERC20_TRANSFER.name
            if obj["_token_id"] is not None:
                return TransferType.ERC721_TRANSFER.name
            return TransferType.UNKNOWN.name

    def get_transfer_id(self, obj: TransferDict) -> str:
        # Remove 0x on transaction_hash
        transaction_hash = obj["transaction_hash"][2:]
        if self.get_type(obj) == "ETHER_TRANSFER":
            return "i" + transaction_hash + obj["_trace_address"]
        else:
            return "e" + transaction_hash + str(obj["_log_index"])

    def validate(self, attrs):
        super().validate(attrs)
        if attrs["value"] is None and attrs["token_id"] is None:
            raise ValidationError("Both value and token_id cannot be null")
        return attrs


class TransferWithTokenInfoResponseSerializer(TransferResponseSerializer):
    token_info = TokenInfoResponseSerializer(source="token")

    def get_type(self, obj: TransferDict) -> str:
        """
        Sometimes ERC20/721 `Transfer` events look the same, if token info is available better use that information
        to check

        :param obj:
        :return: `TransferType` as a string
        """
        transfer_type = super().get_type(obj)
        if transfer_type in (
            TransferType.ERC20_TRANSFER.name,
            TransferType.ERC721_TRANSFER.name,
        ):
            if token := obj["token"]:
                decimals = (
                    token["decimals"] if isinstance(token, dict) else token.decimals
                )
                if decimals is None:
                    transfer_type = TransferType.ERC721_TRANSFER.name
                    if obj["_token_id"] is None:
                        obj["_token_id"], obj["_value"] = (
                            obj["_value"],
                            obj["_token_id"],
                        )
                else:
                    transfer_type = TransferType.ERC20_TRANSFER.name
                    if obj["_value"] is None:
                        obj["_token_id"], obj["_value"] = (
                            obj["_value"],
                            obj["_token_id"],
                        )
        return transfer_type


# All txs serializers
class TxType(Enum):
    ETHEREUM_TRANSACTION = 0
    MULTISIG_TRANSACTION = 1
    MODULE_TRANSACTION = 2


class SafeModuleTransactionWithTransfersResponseSerializer(
    SafeModuleTransactionResponseSerializer
):
    class Meta:
        model = SafeModuleTransactionResponseSerializer.Meta.model
        fields = SafeModuleTransactionResponseSerializer.Meta.fields + (
            "transfers",
            "tx_type",
        )

    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj):
        return TxType.MODULE_TRANSACTION.name


class SafeMultisigTransactionWithTransfersResponseSerializer(
    SafeMultisigTransactionResponseSerializer
):
    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj):
        return TxType.MULTISIG_TRANSACTION.name


class EthereumTxWithTransfersResponseSerializer(serializers.Serializer):
    class Meta:
        model = EthereumTx
        exclude = ("block",)

    execution_date = serializers.DateTimeField()
    _from = EthereumAddressField(
        allow_null=False, allow_zero_address=True, source="_from"
    )
    to = EthereumAddressField(allow_null=True, allow_zero_address=True)
    data = HexadecimalField()
    tx_hash = HexadecimalField()
    block_number = serializers.SerializerMethodField()
    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj) -> str:
        return TxType.ETHEREUM_TRANSACTION.name

    def get_fields(self):
        result = super().get_fields()
        # Rename `_from` to `from`
        _from = result.pop("_from")
        result["from"] = _from
        return result

    def get_block_number(self, obj: EthereumTx) -> Optional[int]:
        if obj.block_id:
            return obj.block_id


class AllTransactionsSchemaSerializer(serializers.Serializer):
    """
    Just for the purpose of documenting, don't use it
    """

    tx_type_1 = SafeModuleTransactionWithTransfersResponseSerializer()
    tx_type_2 = SafeMultisigTransactionWithTransfersResponseSerializer()
    tx_type_3 = EthereumTxWithTransfersResponseSerializer()


# Deprecated ---------------------------------------------------------------


class SafeDelegateDeleteSerializer(serializers.Serializer):
    """
    Deprecated in favour of DelegateDeleteSerializer
    """

    safe = EthereumAddressField()
    delegate = EthereumAddressField()
    signature = HexadecimalField(min_length=65)

    def get_valid_delegators(
        self,
        ethereum_client: EthereumClient,
        safe_address: ChecksumAddress,
        delegate: ChecksumAddress,
    ) -> List[ChecksumAddress]:
        """
        :param ethereum_client:
        :param safe_address:
        :param delegate:
        :return: Valid delegators for a Safe. A delegate should be able to remove itself
        """
        return get_safe_owners(safe_address) + [delegate]

    def check_signature(
        self,
        ethereum_client: EthereumClient,
        safe_address: ChecksumAddress,
        signature: bytes,
        operation_hash: bytes,
        valid_delegators: List[ChecksumAddress],
    ) -> Optional[ChecksumAddress]:
        """
        Checks signature and returns a valid owner if found, None otherwise

        :param ethereum_client:
        :param safe_address:
        :param signature:
        :param operation_hash:
        :param valid_delegators:
        :return: Valid delegator address if found, None otherwise
        """
        safe_signatures = SafeSignature.parse_signature(signature, operation_hash)
        if not safe_signatures:
            raise ValidationError("Signature is not valid")

        if len(safe_signatures) > 1:
            raise ValidationError(
                "More than one signatures detected, just one is expected"
            )

        safe_signature = safe_signatures[0]
        delegator = safe_signature.owner
        if delegator in valid_delegators:
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature of type={safe_signature.signature_type.name} "
                    f"for delegator={delegator} is not valid"
                )
            return delegator

    def validate(self, attrs):
        super().validate(attrs)

        safe_address = attrs["safe"]
        if not SafeContract.objects.filter(address=safe_address).exists():
            raise ValidationError(
                f"Safe={safe_address} does not exist or it's still not indexed"
            )

        signature = attrs["signature"]
        delegate = attrs["delegate"]  # Delegate address to be added/removed

        ethereum_client = EthereumClientProvider()
        valid_delegators = self.get_valid_delegators(
            ethereum_client, safe_address, delegate
        )

        # Tries to find a valid delegator using multiple strategies
        for operation_hash in DelegateSignatureHelper.calculate_all_possible_hashes(
            delegate
        ):
            delegator = self.check_signature(
                ethereum_client,
                safe_address,
                signature,
                operation_hash,
                valid_delegators,
            )
            if delegator:
                break

        if not delegator:
            raise ValidationError("Signing owner is not an owner of the Safe")

        attrs["delegator"] = delegator
        return attrs
