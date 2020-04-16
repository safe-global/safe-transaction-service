from enum import Enum
from typing import Any, Dict, Optional

from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClientProvider
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField)
from gnosis.safe import Safe
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType
from gnosis.safe.serializers import SafeMultisigTxSerializerV1

from .helpers import DelegateSignatureHelper
from .indexers.tx_decoder import TxDecoderException, get_tx_decoder
from .models import (ConfirmationType, ModuleTransaction, MultisigConfirmation,
                     MultisigTransaction, SafeContract, SafeContractDelegate)


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeMultisigTransactionSerializer(SafeMultisigTxSerializerV1):
    contract_transaction_hash = Sha3HashField()
    sender = EthereumAddressField()
    # TODO Make signature mandatory
    signature = HexadecimalField(required=False, min_length=130)  # Signatures must be at least 65 bytes
    origin = serializers.CharField(max_length=100, allow_null=True, default=None)

    def validate(self, data):
        super().validate(data)

        ethereum_client = EthereumClientProvider()
        safe = Safe(data['safe'], ethereum_client)
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safe_tx_gas'], data['base_gas'], data['gas_price'],
                                         data['gas_token'],
                                         data['refund_receiver'], safe_nonce=data['nonce'])
        contract_transaction_hash = safe_tx.safe_tx_hash

        # Check safe tx hash matches
        if contract_transaction_hash != data['contract_transaction_hash']:
            raise ValidationError(f'Contract-transaction-hash={contract_transaction_hash.hex()} '
                                  f'does not match provided contract-tx-hash={data["contract_transaction_hash"].hex()}')

        # Check there's not duplicated tx with same `nonce` or same `safeTxHash` for the same Safe.
        # We allow duplicated if existing tx is not executed
        multisig_transactions = MultisigTransaction.objects.filter(
            safe=safe.address,
            nonce=data['nonce']
        ).executed()
        if multisig_transactions:
            for multisig_transaction in multisig_transactions:
                if multisig_transaction.safe_tx_hash == contract_transaction_hash.hex():
                    raise ValidationError(f'Tx with safe-tx-hash={contract_transaction_hash.hex()} '
                                          f'for safe={safe.address} was already executed in '
                                          f'tx-hash={multisig_transaction.ethereum_tx_id}')

            raise ValidationError(f'Tx with nonce={safe_tx.safe_nonce} for safe={safe.address} '
                                  f'already executed in tx-hash={multisig_transactions[0].ethereum_tx_id}')

        # Check owners and pending owners
        try:
            safe_owners = safe.retrieve_owners(block_identifier='pending')
        except BadFunctionCallOutput:  # Error using pending block identifier
            safe_owners = safe.retrieve_owners(block_identifier='latest')

        data['safe_owners'] = safe_owners

        delegates = SafeContractDelegate.objects.get_delegates_for_safe(safe.address)
        allowed_senders = safe_owners + delegates
        if not data['sender'] in allowed_senders:
            raise ValidationError(f'Sender={data["sender"]} is not an owner or delegate. '
                                  f'Current owners={safe_owners}. Delegates={delegates}')

        signature_owners = []
        # TODO Make signature mandatory
        signature = data.get('signature', b'')
        parsed_signatures = SafeSignature.parse_signature(signature, contract_transaction_hash)
        data['parsed_signatures'] = parsed_signatures
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if not safe_signature.is_valid(ethereum_client, safe.address):
                raise ValidationError(f'Signature={safe_signature.signature.hex()} for owner={owner} is not valid')

            if owner in delegates and len(parsed_signatures) > 1:
                raise ValidationError(f'Just one signature is expected if using delegates')
            if owner not in allowed_senders:
                raise ValidationError(f'Signer={owner} is not an owner or delegate. '
                                      f'Current owners={safe_owners}. Delegates={delegates}')
            if owner in signature_owners:
                raise ValidationError(f'Signature for owner={owner} is duplicated')

            signature_owners.append(owner)

        # TODO Make signature mandatory. len(signature_owners) must be >= 1
        if signature_owners and data['sender'] not in signature_owners:
            raise ValidationError(f'Signature does not match sender={data["sender"]}. '
                                  f'Calculated owners={signature_owners}')

        return data

    def save(self, **kwargs):
        safe_tx_hash = self.validated_data['contract_transaction_hash']
        multisig_transaction, _ = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=safe_tx_hash,
            defaults={
                'safe': self.validated_data['safe'],
                'to': self.validated_data['to'],
                'value': self.validated_data['value'],
                'data': self.validated_data['data'] if self.validated_data['data'] else None,
                'operation': self.validated_data['operation'],
                'safe_tx_gas': self.validated_data['safe_tx_gas'],
                'base_gas': self.validated_data['base_gas'],
                'gas_price': self.validated_data['gas_price'],
                'gas_token': self.validated_data['gas_token'],
                'refund_receiver': self.validated_data['refund_receiver'],
                'nonce': self.validated_data['nonce'],
                'origin': self.validated_data['origin'],
            }
        )

        for safe_signature in self.validated_data.get('parsed_signatures'):
            owner = safe_signature.owner
            if safe_signature.owner in self.validated_data['safe_owners']:
                multisig_confirmation, _ = MultisigConfirmation.objects.get_or_create(
                    multisig_transaction_hash=safe_tx_hash,
                    owner=owner,
                    defaults={
                        'multisig_transaction': multisig_transaction,
                        'signature': safe_signature.export_signature(),
                        'signature_type': safe_signature.signature_type.value,
                    }
                )
        return multisig_transaction


class SafeDelegateDeleteSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    delegate = EthereumAddressField()
    signature = HexadecimalField(min_length=130)

    def validate(self, data):
        super().validate(data)

        if not SafeContract.objects.filter(address=data['safe']).exists():
            raise ValidationError(f"Safe={data['safe']} does not exist or it's still not indexed")

        ethereum_client = EthereumClientProvider()
        safe = Safe(data['safe'], ethereum_client)

        # Check owners and pending owners
        try:
            safe_owners = safe.retrieve_owners(block_identifier='pending')
        except BadFunctionCallOutput:  # Error using pending block identifier
            safe_owners = safe.retrieve_owners(block_identifier='latest')

        signature = data['signature']
        delegate = data['delegate']
        operation_hash = DelegateSignatureHelper.calculate_hash(delegate)
        safe_signatures = SafeSignature.parse_signature(signature, operation_hash)
        if not safe_signatures:
            raise ValidationError('Cannot a valid signature')
        elif len(safe_signatures) > 1:
            raise ValidationError('More than one signatures detected, just one is expected')

        safe_signature = safe_signatures[0]
        delegator = safe_signature.owner
        if delegator not in safe_owners:
            if safe_signature.signature_type == SafeSignatureType.EOA:
                # Maybe it's an `eth_sign` signature without Gnosis Safe `v + 4`, let's try
                safe_signatures = SafeSignature.parse_signature(signature,
                                                                DelegateSignatureHelper.calculate_hash(delegate,
                                                                                                       eth_sign=True))
                safe_signature = safe_signatures[0]
                delegator = safe_signature.owner
            if delegator not in safe_owners:
                raise ValidationError('Signing owner is not an owner of the Safe')

        if not safe_signature.is_valid():
            raise ValidationError(f'Signature of type={safe_signature.signature_type.name} for delegator={delegator} '
                                  f'is not valid')

        data['delegator'] = delegator
        return data


class SafeDelegateSerializer(SafeDelegateDeleteSerializer):
    label = serializers.CharField(max_length=50)

    def save(self, **kwargs):
        safe_address = self.validated_data['safe']
        delegate = self.validated_data['delegate']
        delegator = self.validated_data['delegator']
        label = self.validated_data['label']
        obj, _ = SafeContractDelegate.objects.update_or_create(
            safe_contract_id=safe_address,
            delegate=delegate,
            defaults={
                'label': label,
                'delegator': delegator,
            }
        )
        return obj


# ================================================ #
#            Response Serializers
# ================================================ #
class SafeModuleTransactionResponseSerializer(serializers.ModelSerializer):
    data = HexadecimalField(allow_null=True, allow_blank=True)
    transaction_hash = serializers.SerializerMethodField()
    block_number = serializers.SerializerMethodField()

    class Meta:
        model = ModuleTransaction
        fields = ('created', 'block_number', 'transaction_hash', 'safe',
                  'module', 'to', 'value', 'data', 'operation')

    def get_block_number(self, obj: ModuleTransaction) -> Optional[int]:
        return obj.internal_tx.ethereum_tx.block_id

    def get_transaction_hash(self, obj: ModuleTransaction) -> str:
        return obj.internal_tx.ethereum_tx_id


class SafeMultisigConfirmationResponseSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')
    confirmation_type = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField()
    signature = HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'transaction_hash', 'confirmation_type', 'signature', 'signature_type')

    def get_confirmation_type(self, obj: MultisigConfirmation) -> str:
        # TODO Remove this field
        return ConfirmationType.CONFIRMATION.name

    def get_transaction_hash(self, obj: MultisigConfirmation) -> str:
        return obj.ethereum_tx_id

    def get_signature_type(self, obj: MultisigConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeMultisigTransactionResponseSerializer(SafeMultisigTxSerializerV1):
    execution_date = serializers.DateTimeField()
    submission_date = serializers.DateTimeField(source='created')  # First seen by this service
    modified = serializers.DateTimeField()
    block_number = serializers.SerializerMethodField()
    transaction_hash = Sha3HashField(source='ethereum_tx_id')
    safe_tx_hash = Sha3HashField()
    executor = serializers.SerializerMethodField()
    value = serializers.CharField()
    is_executed = serializers.BooleanField(source='executed')
    is_successful = serializers.SerializerMethodField()
    gas_price = serializers.CharField()
    eth_gas_price = serializers.SerializerMethodField()
    gas_used = serializers.SerializerMethodField()
    fee = serializers.SerializerMethodField()
    origin = serializers.CharField()
    data_decoded = serializers.SerializerMethodField()
    confirmations_required = serializers.IntegerField()
    confirmations = serializers.SerializerMethodField()
    signatures = HexadecimalField()

    def get_block_number(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx_id:
            return obj.ethereum_tx.block_id

    def get_confirmations(self, obj: MultisigTransaction) -> Dict[str, Any]:
        """
        Filters confirmations queryset
        :param obj: MultisigConfirmation instance
        :return: Serialized queryset
        """
        return SafeMultisigConfirmationResponseSerializer(obj.confirmations, many=True).data

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

    def get_gas_used(self, obj: MultisigTransaction) -> Optional[int]:
        if obj.ethereum_tx and obj.ethereum_tx.gas_used:
            return obj.ethereum_tx.gas_used

    def get_is_successful(self, obj: MultisigTransaction) -> Optional[bool]:
        if obj.failed is None:
            return None
        else:
            return not obj.failed

    def get_data_decoded(self, obj: MultisigTransaction) -> Dict[str, Any]:
        tx_decoder = get_tx_decoder()
        try:
            fn_name, types = tx_decoder.decode_transaction_with_types(obj.data.tobytes() if obj.data else b'')
            return {fn_name: types}
        except TxDecoderException:
            return None


class Erc20InfoSerializer(serializers.Serializer):
    name = serializers.CharField()
    symbol = serializers.CharField()
    decimals = serializers.IntegerField()


class SafeBalanceResponseSerializer(serializers.Serializer):
    token_address = serializers.CharField()
    token = Erc20InfoSerializer()
    balance = serializers.CharField()


class SafeBalanceUsdResponseSerializer(SafeBalanceResponseSerializer):
    balance_usd = serializers.CharField()


class SafeDelegateResponseSerializer(serializers.Serializer):
    delegate = EthereumAddressField()
    delegator = EthereumAddressField()
    label = serializers.CharField(max_length=50)


class SafeCreationInfoResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    creator = EthereumAddressField()
    factory_address = EthereumAddressField()
    master_copy = EthereumAddressField(allow_null=True)
    setup_data = HexadecimalField(allow_null=True)
    transaction_hash = Sha3HashField()


class OwnerResponseSerializer(serializers.Serializer):
    safes = serializers.ListField(child=EthereumAddressField())


class IncomingTransactionType(Enum):
    ETHER_TRANSFER = 0
    ERC20_TRANSFER = 1
    ERC721_TRANSFER = 2
    UNKNOWN = 3


class IncomingTransactionResponseSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    execution_date = serializers.DateTimeField()
    block_number = serializers.IntegerField()
    transaction_hash = Sha3HashField()
    to = EthereumAddressField()
    from_ = EthereumAddressField(source='_from')
    value = serializers.CharField()
    token_id = serializers.CharField()
    token_address = EthereumAddressField(allow_null=True, default=None)

    def get_fields(self):
        result = super().get_fields()
        # Rename `from_` to `from`
        from_ = result.pop('from_')
        result['from'] = from_
        return result

    def get_type(self, obj: Dict[str, Any]) -> str:
        if not obj.get('token_address'):
            return IncomingTransactionType.ETHER_TRANSFER.name
        else:
            if obj.get('value') is not None:
                return IncomingTransactionType.ERC20_TRANSFER.name
            elif obj.get('token_id') is not None:
                return IncomingTransactionType.ERC721_TRANSFER.name

        return IncomingTransactionType.UNKNOWN
