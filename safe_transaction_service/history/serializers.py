import datetime
import itertools
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.http import Http404
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from eth_typing import ChecksumAddress
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField as EthereumAddressDbField,
)
from safe_eth.eth.django.models import Keccak256Field as Keccak256DbField
from safe_eth.eth.django.serializers import (
    EthereumAddressField,
    HexadecimalField,
    Sha3HashField,
)
from safe_eth.safe import Safe, SafeOperationEnum
from safe_eth.safe.safe_signature import EthereumBytes, SafeSignature, SafeSignatureType
from safe_eth.safe.serializers import SafeMultisigTxSerializer
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.account_abstraction import serializers as aa_serializers
from safe_transaction_service.contracts.tx_decoder import (
    TxDecoderException,
    get_db_tx_decoder,
)
from safe_transaction_service.tokens.serializers import TokenInfoResponseSerializer
from safe_transaction_service.utils.serializers import (
    EpochDateTimeField,
    get_safe_owners,
)

from ..contracts.models import Contract
from ..loggers.custom_logger import http_request_log
from .exceptions import NodeConnectionException
from .helpers import (
    DelegateSignatureHelper,
    DelegateSignatureHelperV2,
    DeleteMultisigTxSignatureHelper,
)
from .models import (
    MAX_SIGNATURE_LENGTH,
    EthereumTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    TransferDict,
)
from .services.safe_service import SafeCreationInfo

logger = logging.getLogger(__name__)


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
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)

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
        ethereum_client = get_auto_ethereum_client()
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
            signature, safe_tx_hash, safe_hash_preimage=safe_tx.safe_tx_hash_preimage
        )
        signature_owners = []
        ethereum_client = get_auto_ethereum_client()
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if owner in settings.BANNED_EOAS:
                raise ValidationError(
                    f"Signer={owner} is not authorized to interact with the service"
                )
            if owner not in safe_owners:
                raise ValidationError(
                    f"Signer={owner} is not an owner. Current owners={safe_owners}"
                )
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={to_0x_hex_str(safe_signature.signature)} for owner={owner} is not valid"
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
            multisig_confirmation, created = MultisigConfirmation.objects.get_or_create(
                multisig_transaction_hash=safe_tx_hash,
                owner=safe_signature.owner,
                defaults={
                    "multisig_transaction_id": safe_tx_hash,
                    "signature": safe_signature.export_signature(),
                    "signature_type": safe_signature.signature_type.value,
                },
            )
            logger.info(
                multisig_confirmation.to_log(f"{'Created' if created else 'Updated'}")
            )
            multisig_confirmations.append(multisig_confirmation)

        if self.validated_data["signature"]:
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).update(
                trusted=True
            )
        return multisig_confirmations


class SafeMultisigTransactionSerializer(SafeMultisigTxSerializer):
    to = EthereumAddressField(allow_zero_address=True, allow_sentinel_address=True)
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

        tx_to = attrs["to"]
        tx_operation = attrs["operation"]
        if (
            settings.DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION
            and tx_operation == SafeOperationEnum.DELEGATE_CALL.value
            and tx_to not in Contract.objects.trusted_addresses_for_delegate_call()
        ):
            raise ValidationError("Operation DELEGATE_CALL is not allowed")

        ethereum_client = get_auto_ethereum_client()
        safe_address = attrs["safe"]

        safe = Safe(safe_address, ethereum_client)
        safe_tx = safe.build_multisig_tx(
            tx_to,
            attrs["value"],
            attrs["data"],
            tx_operation,
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
                f"Contract-transaction-hash={to_0x_hex_str(safe_tx_hash)} "
                f'does not match provided contract-tx-hash={to_0x_hex_str(attrs["contract_transaction_hash"])}'
            )

        # Check there's not duplicated tx with same `nonce` or same `safeTxHash` for the same Safe.
        # We allow duplicated if existing tx is not executed
        multisig_transactions = MultisigTransaction.objects.filter(
            safe=safe_address, nonce=attrs["nonce"]
        ).executed()
        if multisig_transactions:
            for multisig_transaction in multisig_transactions:
                if multisig_transaction.safe_tx_hash == to_0x_hex_str(safe_tx_hash):
                    raise ValidationError(
                        f"Tx with safe-tx-hash={to_0x_hex_str(safe_tx_hash)} "
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
                    f"Signature={to_0x_hex_str(safe_signature.signature)} for owner={owner} is not valid"
                )

            if owner in settings.BANNED_EOAS:
                raise ValidationError(
                    f"Signer={owner} is not authorized to interact with the service"
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

        proposed_by_delegate = None
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
            proposed_by_delegate = self.validated_data["sender"]

        multisig_transaction, created = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=safe_tx_hash,
            defaults={
                "safe": self.validated_data["safe"],
                "to": self.validated_data["to"],
                "value": self.validated_data["value"],
                "data": (
                    self.validated_data["data"] if self.validated_data["data"] else None
                ),
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
                "proposed_by_delegate": proposed_by_delegate,
            },
        )

        if not created and trusted and not multisig_transaction.trusted:
            multisig_transaction.origin = origin
            multisig_transaction.trusted = trusted
            multisig_transaction.save(update_fields=["origin", "trusted"])

        logger.info(
            f"MultisigTransaction {"Created" if created else "Updated"}",
            extra={
                "http_request": http_request_log(request),
                "extra_data": multisig_transaction.to_dict(),
            },
        )

        for safe_signature in self.validated_data.get("parsed_signatures"):
            if safe_signature.owner in self.validated_data["safe_owners"]:
                multisig_confirmation, created = (
                    MultisigConfirmation.objects.get_or_create(
                        multisig_transaction_hash=safe_tx_hash,
                        owner=safe_signature.owner,
                        defaults={
                            "multisig_transaction": multisig_transaction,
                            "signature": safe_signature.export_signature(),
                            "signature_type": safe_signature.signature_type.value,
                        },
                    )
                )
                logger.info(
                    f"MultisigConfirmation {'Created' if created else 'Updated'}",
                    extra={
                        "http_request": http_request_log(request),
                        "extra_data": multisig_confirmation.to_dict(),
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
        ethereum_client = get_auto_ethereum_client()
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


class DelegateSerializerMixin:
    """
    Mixin to validate delegate operations data
    """

    def validate_safe_address_and_delegator(
        self, safe_address: ChecksumAddress, delegator: ChecksumAddress
    ) -> None:
        if (
            safe_address
            and not SafeContract.objects.filter(address=safe_address).exists()
        ):
            raise ValidationError(
                f"Safe={safe_address} does not exist or it's still not indexed"
            )

        if safe_address:
            # Valid delegators must be owners
            valid_delegators = get_safe_owners(safe_address)
            if delegator not in valid_delegators:
                raise ValidationError(
                    f"Provided delegator={delegator} is not an owner of Safe={safe_address}"
                )

    def validate_delegator_signature(
        self,
        delegate: ChecksumAddress,
        signature: EthereumBytes,
        signer: ChecksumAddress,
    ) -> bool:
        ethereum_client = get_auto_ethereum_client()
        chain_id = ethereum_client.get_chain_id()
        # Accept a message with the current topt and the previous totp (to prevent replay attacks)
        for previous_totp, chain_id in list(
            itertools.product((True, False), (chain_id, None))
        ):
            message_hash = DelegateSignatureHelperV2.calculate_hash(
                delegate, chain_id, previous_totp=previous_totp
            )
            safe_signatures = SafeSignature.parse_signature(signature, message_hash)
            if not safe_signatures:
                raise ValidationError("Signature is not valid")

            if len(safe_signatures) > 1:
                raise ValidationError(
                    "More than one signatures detected, just one is expected"
                )
            safe_signature = safe_signatures[0]
            owner = safe_signature.owner
            if not safe_signature.is_valid(ethereum_client, owner):
                raise ValidationError(
                    f"Signature of type={safe_signature.signature_type.name} "
                    f"for signer={signer} is not valid"
                )
            if owner == signer:
                return True
        return False


class DelegateSerializerV2(DelegateSerializerMixin, serializers.Serializer):
    safe = EthereumAddressField(allow_null=True, required=False, default=None)
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)
    label = serializers.CharField(max_length=50)
    expiry_date = serializers.DateTimeField(
        allow_null=True, required=False, default=None
    )

    def validate_expiry_date(
        self, expiry_date: Optional[datetime.datetime]
    ) -> Optional[datetime.datetime]:
        """
        Make sure ``expiry_date`` is not previous to the current timestamp

        :param expiry_date:
        :return: `expiry_date`
        """
        if expiry_date and expiry_date <= timezone.now():
            raise ValidationError(
                "`expiry_date` cannot be previous to the current timestamp"
            )
        return expiry_date

    def validate(self, attrs):
        super().validate(attrs)
        safe_address: Optional[ChecksumAddress] = attrs.get("safe")
        signature = attrs["signature"]
        delegate = attrs["delegate"]
        delegator = attrs["delegator"]
        self.validate_safe_address_and_delegator(safe_address, delegator)
        if self.validate_delegator_signature(
            delegate=delegate, signature=signature, signer=delegator
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
        expiry_date = self.validated_data["expiry_date"]
        obj, _ = SafeContractDelegate.objects.update_or_create(
            safe_contract_id=safe_address,
            delegate=delegate,
            delegator=delegator,
            defaults={
                "label": label,
                "expiry_date": expiry_date,
            },
        )
        return obj


class DelegateDeleteSerializerV2(DelegateSerializerMixin, serializers.Serializer):
    safe = EthereumAddressField(allow_null=True, required=False, default=None)
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)

    def validate(self, attrs):
        super().validate(attrs)
        safe_address: Optional[ChecksumAddress] = attrs.get("safe")
        signature = attrs["signature"]
        delegate = self.context["request"].parser_context["kwargs"]["delegate_address"]
        delegator = attrs["delegator"]
        self.validate_safe_address_and_delegator(safe_address, delegator)
        if self.validate_delegator_signature(
            delegate, signature, delegator
        ) or self.validate_delegator_signature(delegate, signature, delegate):
            return attrs

        raise ValidationError(
            f"Signature does not match provided delegate={delegate} or delegator={delegator}"
        )


class SafeMultisigTransactionDeleteSerializer(serializers.Serializer):
    safe_tx_hash = Sha3HashField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)

    def validate(self, attrs):
        super().validate(attrs)
        safe_tx_hash = attrs["safe_tx_hash"]
        signature = attrs["signature"]

        try:
            multisig_tx = MultisigTransaction.objects.select_related("ethereum_tx").get(
                safe_tx_hash=safe_tx_hash
            )
        except MultisigTransaction.DoesNotExist:
            raise Http404("Multisig transaction not found")

        if multisig_tx.executed:
            raise ValidationError("Executed transactions cannot be deleted")

        proposer = multisig_tx.proposer
        if not proposer or proposer == NULL_ADDRESS:
            raise ValidationError("Old transactions without proposer cannot be deleted")

        ethereum_client = get_auto_ethereum_client()
        chain_id = ethereum_client.get_chain_id()
        safe_address = multisig_tx.safe
        # Accept a message with the current topt and the previous totp (to prevent replay attacks)
        for previous_totp in (True, False):
            message_hash = DeleteMultisigTxSignatureHelper.calculate_hash(
                safe_address, safe_tx_hash, chain_id, previous_totp=previous_totp
            )
            safe_signatures = SafeSignature.parse_signature(signature, message_hash)
            if len(safe_signatures) != 1:
                raise ValidationError(
                    f"1 owner signature was expected, {len(safe_signatures)} received"
                )
            safe_signature = safe_signatures[0]
            # Currently almost all the transactions are proposed using EOAs. Adding support for EIP1271, for example,
            # would require to use the EIP712 domain of the Safe and a blockchain check. For starting
            # with this feature we will try to keep it simple and only support EOA signatures.
            if safe_signature.signature_type not in (
                SafeSignatureType.EOA,
                SafeSignatureType.ETH_SIGN,
            ):
                raise ValidationError("Only EOA and ETH_SIGN signatures are supported")

            # The transaction can be deleted by the proposer or by the delegate user who proposed it.
            owner = safe_signature.owner
            if owner == proposer:
                return attrs

            proposed_by_delegate = multisig_tx.proposed_by_delegate
            if proposed_by_delegate and owner == proposed_by_delegate:
                delegates_for_proposer = (
                    SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                        safe_address, [proposer]
                    )
                )
                # Check if it's still a valid delegate.
                if owner in delegates_for_proposer:
                    return attrs

        raise ValidationError(
            "Provided signer is not the proposer or the delegate user who proposed the transaction"
        )


class DataDecoderSerializer(serializers.Serializer):
    data = HexadecimalField(allow_null=False, allow_blank=False, min_length=4)
    to = EthereumAddressField(allow_null=True, required=False)


# ================================================ #
#            Response Serializers
# ================================================ #
class SafeDelegateResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField(source="safe_contract_id")
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    label = serializers.CharField(max_length=50)
    expiry_date = serializers.DateTimeField()


class SafeModuleTransactionResponseSerializer(GnosisBaseModelSerializer):
    execution_date = serializers.DateTimeField()
    data = HexadecimalField(allow_null=True, allow_blank=True)
    data_decoded = serializers.SerializerMethodField()
    transaction_hash = HexadecimalField(source="internal_tx.ethereum_tx_id")
    block_number = serializers.IntegerField(source="internal_tx.block_number")
    is_successful = serializers.SerializerMethodField()
    module_transaction_id = serializers.CharField(
        source="unique_id",
        help_text="Internally calculated parameter to uniquely identify a moduleTransaction \n"
        "`ModuleTransactionId = i+tx_hash+trace_address`",
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

    def get_data_decoded(self, obj: ModuleTransaction) -> Dict[str, Any]:
        return get_data_decoded_from_data(obj.data if obj.data else b"", address=obj.to)

    def get_is_successful(self, obj: ModuleTransaction) -> bool:
        return not obj.failed


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


class SafeMultisigTransactionResponseSerializer(SafeMultisigTxSerializer):
    execution_date = serializers.DateTimeField()
    submission_date = serializers.DateTimeField(
        source="created"
    )  # First seen by this service
    modified = serializers.DateTimeField()
    block_number = serializers.SerializerMethodField()
    transaction_hash = Sha3HashField(source="ethereum_tx_id")
    safe_tx_hash = Sha3HashField()
    proposer = EthereumAddressField()
    proposed_by_delegate = EthereumAddressField(allow_null=True)
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
    signatures = serializers.SerializerMethodField()

    def get_block_number(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx_id:
            return obj.ethereum_tx.block_id

    def get_confirmations(self, obj: MultisigTransaction) -> Dict[str, Any]:
        """
        Validate and check integrity of confirmations queryset

        :param obj: MultisigConfirmation instance
        :return: Serialized queryset
        :raises InternalValidationError: If any inconsistency is detected
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
                obj.data if obj.data else b"", address=obj.to
            )

    @extend_schema_field(HexadecimalField(allow_null=True, required=False))
    def get_signatures(self, obj: MultisigTransaction):
        return to_0x_hex_str(obj.signatures) if obj.signatures else None


class SafeMultisigTransactionResponseSerializerV2(
    SafeMultisigTransactionResponseSerializer
):
    nonce = serializers.CharField()
    base_gas = serializers.CharField()
    safe_tx_gas = serializers.CharField()


class IndexingStatusSerializer(serializers.Serializer):
    current_block_number = serializers.IntegerField()
    current_block_timestamp = EpochDateTimeField()
    erc20_block_number = serializers.IntegerField()
    erc20_block_timestamp = EpochDateTimeField()
    erc20_synced = serializers.BooleanField()
    master_copies_block_number = serializers.IntegerField()
    master_copies_block_timestamp = EpochDateTimeField()
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


class SafeCreationInfoResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    creator = EthereumAddressField()
    transaction_hash = Sha3HashField()
    factory_address = EthereumAddressField()
    master_copy = EthereumAddressField(allow_null=True)
    setup_data = HexadecimalField(allow_null=True)
    salt_nonce = serializers.CharField(allow_null=True)
    data_decoded = serializers.SerializerMethodField()
    user_operation = aa_serializers.UserOperationWithSafeOperationResponseSerializer(
        allow_null=True
    )

    def get_data_decoded(self, obj: SafeCreationInfo) -> Dict[str, Any]:
        return get_data_decoded_from_data(obj.setup_data or b"")


class SafeInfoResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    nonce = serializers.CharField()
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
        transaction_hash = obj["transaction_hash"][2:]  # Remove 0x
        if self.get_type(obj) == TransferType.ETHER_TRANSFER.name:
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


class SafeMultisigTransactionWithTransfersResponseSerializerV2(
    SafeMultisigTransactionResponseSerializerV2
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


class AllTransactionsSchemaSerializerV2(serializers.Serializer):
    """
    Just for the purpose of documenting, don't use it
    """

    tx_type_1 = SafeModuleTransactionWithTransfersResponseSerializer()
    tx_type_2 = SafeMultisigTransactionWithTransfersResponseSerializerV2()
    tx_type_3 = EthereumTxWithTransfersResponseSerializer()


# Deprecated ---------------------------------------------------------------


class SafeDelegateDeleteSerializer(serializers.Serializer):
    """
    .. deprecated:: 3.3.0
       Deprecated in favour of DelegateDeleteSerializer
    """

    safe = EthereumAddressField()
    delegate = EthereumAddressField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)

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

        ethereum_client = get_auto_ethereum_client()
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


class DelegateSignatureCheckerMixin:
    """
    Mixin to include delegate signature validation
    .. deprecated:: 4.38.0
       Deprecated in favour of DelegateSerializerMixin
    """

    def check_delegate_signature(
        self,
        ethereum_client: EthereumClient,
        signature: bytes,
        operation_hash: bytes,
        delegator: ChecksumAddress,
    ) -> bool:
        """
        Verifies signature to check if it matches the delegator

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
    """
    .. deprecated:: 4.38.0
       Deprecated in favour of DelegateSerializerV2
    """

    safe = EthereumAddressField(allow_null=True, required=False, default=None)
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)
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

        ethereum_client = get_auto_ethereum_client()
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
    """
    .. deprecated:: 4.38.0
       Deprecated in favour of DelegateDeleteSerializerV2
    """

    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    signature = HexadecimalField(min_length=65, max_length=MAX_SIGNATURE_LENGTH)

    def validate(self, attrs):
        super().validate(attrs)

        signature = attrs["signature"]
        delegate = attrs["delegate"]  # Delegate address to be added/removed
        delegator = attrs["delegator"]  # Delegator

        ethereum_client = get_auto_ethereum_client()
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


class SafeDeploymentContractSerializer(serializers.Serializer):
    contract_name = serializers.CharField()
    address = EthereumAddressField(allow_null=True)


class SafeDeploymentSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=10)  # Example 1.3.0
    contracts = SafeDeploymentContractSerializer(many=True)


class CodeErrorResponse(serializers.Serializer):
    code = serializers.IntegerField()
    message = serializers.CharField()
    arguments = serializers.ListField()
