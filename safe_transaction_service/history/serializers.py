from enum import Enum
from typing import Any, Dict, List, Optional

from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClientProvider
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField)
from gnosis.safe import Safe
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType
from gnosis.safe.serializers import SafeMultisigTxSerializerV1

from safe_transaction_service.tokens.serializers import \
    TokenInfoResponseSerializer

from .helpers import DelegateSignatureHelper
from .indexers.tx_decoder import TxDecoderException, get_db_tx_decoder
from .models import (ConfirmationType, EthereumTx, ModuleTransaction,
                     MultisigConfirmation, MultisigTransaction, SafeContract,
                     SafeContractDelegate)
from .services.safe_service import SafeCreationInfo


def get_data_decoded_from_data(data: bytes):
    tx_decoder = get_db_tx_decoder()
    try:
        return tx_decoder.get_data_decoded(data)
    except TxDecoderException:
        return None


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeMultisigConfirmationSerializer(serializers.Serializer):
    signature = HexadecimalField(min_length=65)  # Signatures must be at least 65 bytes

    def validate_signature(self, signature: bytes):
        safe_tx_hash = self.context['safe_tx_hash']
        try:
            multisig_transaction = MultisigTransaction.objects.select_related(
                'ethereum_tx'
            ).get(safe_tx_hash=safe_tx_hash)
        except MultisigTransaction.DoesNotExist:
            raise NotFound(f'Multisig transaction with safe-tx-hash={safe_tx_hash} was not found')

        safe_address = multisig_transaction.safe
        if multisig_transaction.executed:
            raise ValidationError(f'Transaction with safe-tx-hash={safe_tx_hash} was already executed')

        ethereum_client = EthereumClientProvider()
        safe = Safe(safe_address, ethereum_client)
        try:
            safe_owners = safe.retrieve_owners(block_identifier='pending')
        except BadFunctionCallOutput:  # Error using pending block identifier
            safe_owners = safe.retrieve_owners(block_identifier='latest')

        parsed_signatures = SafeSignature.parse_signature(signature, safe_tx_hash)
        signature_owners = []
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if owner not in safe_owners:
                raise ValidationError(f'Signer={owner} is not an owner. Current owners={safe_owners}')
            if not safe_signature.is_valid(ethereum_client, safe.address):
                raise ValidationError(f'Signature={safe_signature.signature.hex()} for owner={owner} is not valid')
            if owner in signature_owners:
                raise ValidationError(f'Signature for owner={owner} is duplicated')

            signature_owners.append(owner)
        return signature

    def save(self, **kwargs):
        safe_tx_hash = self.context['safe_tx_hash']
        signature = self.validated_data['signature']
        multisig_confirmations = []
        parsed_signatures = SafeSignature.parse_signature(signature, safe_tx_hash)
        for safe_signature in parsed_signatures:
            multisig_confirmation, _ = MultisigConfirmation.objects.get_or_create(
                multisig_transaction_hash=safe_tx_hash,
                owner=safe_signature.owner,
                defaults={
                    'multisig_transaction_id': safe_tx_hash,
                    'signature': safe_signature.export_signature(),
                    'signature_type': safe_signature.signature_type.value,
                }
            )
            multisig_confirmations.append(multisig_confirmation)

        if self.validated_data['signature']:
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).update(trusted=True)
        return multisig_confirmations


class SafeMultisigTransactionSerializer(SafeMultisigTxSerializerV1):
    contract_transaction_hash = Sha3HashField()
    sender = EthereumAddressField()
    # TODO Make signature mandatory
    signature = HexadecimalField(required=False, min_length=65)  # Signatures must be at least 65 bytes
    origin = serializers.CharField(max_length=100, allow_null=True, default=None)

    def validate(self, data):
        super().validate(data)

        ethereum_client = EthereumClientProvider()
        safe = Safe(data['safe'], ethereum_client)
        try:
            safe_version = safe.retrieve_version()
        except BadFunctionCallOutput as e:
            raise ValidationError(f'Could not get Safe version from blockchain, check contract exists on network '
                                  f'{ethereum_client.get_network().name}') from e

        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safe_tx_gas'], data['base_gas'], data['gas_price'],
                                         data['gas_token'],
                                         data['refund_receiver'],
                                         safe_nonce=data['nonce'],
                                         safe_version=safe_version)
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
        # If there's at least one signature, transaction is trusted (until signatures are mandatory)
        data['trusted'] = bool(parsed_signatures)
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if not safe_signature.is_valid(ethereum_client, safe.address):
                raise ValidationError(f'Signature={safe_signature.signature.hex()} for owner={owner} is not valid')

            if owner in delegates and len(parsed_signatures) > 1:
                raise ValidationError('Just one signature is expected if using delegates')
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
        origin = self.validated_data['origin']
        trusted = self.validated_data['trusted']
        multisig_transaction, created = MultisigTransaction.objects.get_or_create(
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
                'origin': origin,
                'trusted': trusted,
            }
        )

        if not created and trusted and not multisig_transaction.trusted:
            multisig_transaction.origin = origin
            multisig_transaction.trusted = trusted
            multisig_transaction.save(update_fields=['origin', 'trusted'])

        for safe_signature in self.validated_data.get('parsed_signatures'):
            if safe_signature.owner in self.validated_data['safe_owners']:
                multisig_confirmation, _ = MultisigConfirmation.objects.get_or_create(
                    multisig_transaction_hash=safe_tx_hash,
                    owner=safe_signature.owner,
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
    signature = HexadecimalField(min_length=65)

    def check_signature(self, signature: bytes, operation_hash: bytes, safe_owners: List[str]) -> Optional[str]:
        """
        Checks signature and returns a valid owner if found, None otherwise
        :param signature:
        :param operation_hash:
        :param safe_owners:
        :return: Valid delegator address if found, None otherwise
        """
        safe_signatures = SafeSignature.parse_signature(signature, operation_hash)
        if not safe_signatures:
            raise ValidationError('Signature is not valid')
        elif len(safe_signatures) > 1:
            raise ValidationError('More than one signatures detected, just one is expected')

        safe_signature = safe_signatures[0]
        delegator = safe_signature.owner
        if delegator in safe_owners:
            if not safe_signature.is_valid():
                raise ValidationError(f'Signature of type={safe_signature.signature_type.name} '
                                      f'for delegator={delegator} is not valid')
            return delegator

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
        delegate = data['delegate']  # Delegate address to be added

        # Tries to find a valid delegator using multiple strategies
        for operation_hash in (DelegateSignatureHelper.calculate_hash(delegate),
                               DelegateSignatureHelper.calculate_hash(delegate, eth_sign=True),
                               DelegateSignatureHelper.calculate_hash(delegate, previous_topt=True),
                               DelegateSignatureHelper.calculate_hash(delegate, eth_sign=True, previous_topt=True)):
            delegator = self.check_signature(signature, operation_hash, safe_owners)
            if delegator:
                break

        if not delegator:
            raise ValidationError('Signing owner is not an owner of the Safe')

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
    execution_date = serializers.DateTimeField()
    data = HexadecimalField(allow_null=True, allow_blank=True)
    data_decoded = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField()
    block_number = serializers.SerializerMethodField()

    class Meta:
        model = ModuleTransaction
        fields = ('created', 'execution_date', 'block_number', 'transaction_hash', 'safe',
                  'module', 'to', 'value', 'data', 'operation', 'data_decoded')

    def get_block_number(self, obj: ModuleTransaction) -> Optional[int]:
        return obj.internal_tx.ethereum_tx.block_id

    def get_data_decoded(self, obj: SafeCreationInfo) -> Dict[str, Any]:
        return get_data_decoded_from_data(obj.data.tobytes() if obj.data else b'')

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
        return get_data_decoded_from_data(obj.data.tobytes() if obj.data else b'')


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
    balance_usd = serializers.CharField(source='fiat_balance')
    usd_conversion = serializers.CharField(source='fiat_conversion')
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


class SafeDelegateResponseSerializer(serializers.Serializer):
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
        return get_data_decoded_from_data(obj.setup_data or b'')


class SafeInfoResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    nonce = serializers.IntegerField()
    threshold = serializers.IntegerField()
    owners = serializers.ListField(child=EthereumAddressField())
    master_copy = EthereumAddressField()
    modules = serializers.ListField(child=EthereumAddressField())
    fallback_handler = EthereumAddressField()
    version = serializers.CharField()


class MasterCopyResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    version = serializers.CharField()


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
    block_number = serializers.IntegerField()
    transaction_hash = Sha3HashField()
    to = EthereumAddressField()
    from_ = EthereumAddressField(source='_from', allow_zero_address=True)
    value = serializers.CharField(allow_null=True)
    token_id = serializers.CharField(allow_null=True)
    token_address = EthereumAddressField(allow_null=True, default=None)

    def get_fields(self):
        result = super().get_fields()
        # Rename `from_` to `from`
        from_ = result.pop('from_')
        result['from'] = from_
        return result

    def get_type(self, obj: Dict[str, Any]) -> str:
        if not obj.get('token_address'):
            return TransferType.ETHER_TRANSFER.name
        else:
            if obj.get('value') is not None:
                return TransferType.ERC20_TRANSFER.name
            elif obj.get('token_id') is not None:
                return TransferType.ERC721_TRANSFER.name

        return TransferType.UNKNOWN

    def validate(self, data):
        super().validate(data)
        if data['value'] is None and data['token_id'] is None:
            raise ValidationError('Both value and token_id cannot be null')
        return data


class TransferWithTokenInfoResponseSerializer(TransferResponseSerializer):
    token_info = TokenInfoResponseSerializer(source='token')

    def get_type(self, obj: Dict[str, Any]) -> str:
        """
        Sometimes ERC20/721 `Transfer` events look the same, if token info is available better use that information
        to check
        :param obj:
        :return: `TransferType` as a string
        """
        transfer_type = super().get_type(obj)
        if transfer_type in (TransferType.ERC20_TRANSFER.name, TransferType.ERC721_TRANSFER.name):
            if token := obj['token']:
                decimals = token['decimals'] if isinstance(token, dict) else token.decimals
                if decimals is None:
                    transfer_type = TransferType.ERC721_TRANSFER.name
                    if obj['token_id'] is None:
                        obj['token_id'], obj['value'] = obj['value'], obj['token_id']
                else:
                    transfer_type = TransferType.ERC20_TRANSFER.name
                    if obj['value'] is None:
                        obj['token_id'], obj['value'] = obj['value'], obj['token_id']
        return transfer_type


# All txs serializers
class TxType(Enum):
    ETHEREUM_TRANSACTION = 0
    MULTISIG_TRANSACTION = 1
    MODULE_TRANSACTION = 2


class SafeModuleTransactionWithTransfersResponseSerializer(SafeModuleTransactionResponseSerializer):
    class Meta:
        model = SafeModuleTransactionResponseSerializer.Meta.model
        fields = SafeModuleTransactionResponseSerializer.Meta.fields + ('transfers', 'tx_type')

    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj):
        return TxType.MODULE_TRANSACTION.name


class SafeMultisigTransactionWithTransfersResponseSerializer(SafeMultisigTransactionResponseSerializer):
    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj):
        return TxType.MULTISIG_TRANSACTION.name


class EthereumTxWithTransfersResponseSerializer(serializers.Serializer):
    class Meta:
        model = EthereumTx
        exclude = ('block',)

    execution_date = serializers.DateTimeField()
    _from = EthereumAddressField(allow_null=False, allow_zero_address=True, source='_from')
    to = EthereumAddressField(allow_null=True, allow_zero_address=True)
    data = HexadecimalField()
    tx_hash = HexadecimalField()
    block_number = serializers.SerializerMethodField()
    transfers = TransferWithTokenInfoResponseSerializer(many=True)
    tx_type = serializers.SerializerMethodField()

    def get_tx_type(self, obj):
        return TxType.ETHEREUM_TRANSACTION.name

    def get_fields(self):
        result = super().get_fields()
        # Rename `_from` to `from`
        _from = result.pop('_from')
        result['from'] = _from
        return result

    def get_block_number(self, obj: EthereumTx):
        if obj.block_id:
            return obj.block_id


class AnalyticsMultisigTxsByOriginResponseSerializer(serializers.Serializer):
    origin = serializers.CharField()
    transactions = serializers.IntegerField()


class AnalyticsMultisigTxsBySafeResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    master_copy = EthereumAddressField()
    transactions = serializers.IntegerField()


class _AllTransactionsSchemaSerializer(serializers.Serializer):
    """
    Just for the purpose of documenting, don't use it
    """
    tx_type_1 = SafeModuleTransactionWithTransfersResponseSerializer()
    tx_type_2 = SafeMultisigTransactionWithTransfersResponseSerializer()
    tx_type_3 = EthereumTxWithTransfersResponseSerializer()
