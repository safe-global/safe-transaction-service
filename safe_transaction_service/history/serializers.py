from datetime import datetime, timezone
from typing import Any, Dict, Optional

from eth_account import Account
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClientProvider
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField)
from gnosis.safe import Safe
from gnosis.safe.serializers import SafeMultisigTxSerializerV1

from .models import ConfirmationType, MultisigConfirmation, MultisigTransaction


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeMultisigTransactionSerializer(SafeMultisigTxSerializerV1):
    contract_transaction_hash = Sha3HashField()
    sender = EthereumAddressField()
    signature = HexadecimalField(required=False)

    def validate_confirmation_type(self, value: str) -> int:
        value = value.upper()
        try:
            return ConfirmationType[value].name
        except KeyError:
            raise ValidationError(f'Confirmation Type {value} not recognized')

    def validate(self, data):
        super().validate(data)

        signature = data.get('signature')
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

        # Check there's not duplicated tx with same `nonce` for the same Safe.
        # We allow duplicated if existing tx is not executed
        try:
            multisig_transaction: MultisigTransaction = MultisigTransaction.objects.exclude(
                ethereum_tx=None
            ).exclude(
                safe_tx_hash=contract_transaction_hash
            ).get(
                safe=safe.address,
                nonce=data['nonce']
            )
            if HexBytes(multisig_transaction.safe_tx_hash) != contract_transaction_hash:
                raise ValidationError(f'Tx with nonce={safe_tx.safe_nonce} for safe={safe.address} already executed in '
                                      f'tx-hash={multisig_transaction.ethereum_tx_id}')
        except MultisigTransaction.DoesNotExist:
            pass

        # Check owners and old owners, owner might be removed but that tx can still be signed by that owner
        if not safe.retrieve_is_owner(data['sender']):
            try:
                # TODO Fix this, we can use SafeStatus now
                if not safe.retrieve_is_owner(data['sender'],
                                              block_identifier=max(0, ethereum_client.current_block_number - 20)):
                    raise ValidationError('User is not an owner')
            except BadFunctionCallOutput:  # If it didn't exist 20 blocks ago
                raise ValidationError('User is not an owner')

        #  TODO Support contract signatures
        if signature is not None:
            #  TODO Support signatures with multiple owners
            if len(signature) != 65:
                raise ValidationError('Signatures with more than one owner still not supported')

            address = Account.recoverHash(contract_transaction_hash, signature=signature)
            if address != data['sender']:
                raise ValidationError(f'Signature does not match sender={data["sender"]}. Calculated owner={address}')

        return data

    def save(self, **kwargs):
        multisig_transaction, _ = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=self.validated_data['contract_transaction_hash'],
            defaults={
                'safe': self.validated_data['safe'],
                'to': self.validated_data['to'],
                'value': self.validated_data['value'],
                'data': self.validated_data['data'],
                'operation': self.validated_data['operation'],
                'safe_tx_gas': self.validated_data['safe_tx_gas'],
                'base_gas': self.validated_data['base_gas'],
                'gas_price': self.validated_data['gas_price'],
                'gas_token': self.validated_data['gas_token'],
                'refund_receiver': self.validated_data['refund_receiver'],
                'nonce': self.validated_data['nonce']
            }
        )

        if self.validated_data.get('signature'):
            MultisigConfirmation.objects.get_or_create(
                multisig_transaction_hash=multisig_transaction.safe_tx_hash,
                owner=self.validated_data['sender'],
                defaults={
                    'multisig_transaction': multisig_transaction,
                    'signature': self.validated_data.get('signature'),
                }
            )
        return multisig_transaction


# ================================================ #
#            Response Serializers
# ================================================ #
class SafeMultisigConfirmationResponseSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')
    confirmation_type = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField()
    signature = HexadecimalField()

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'transaction_hash', 'confirmation_type', 'signature')

    def get_confirmation_type(self, obj: MultisigConfirmation):
        #TODO Remove this field
        return ConfirmationType.CONFIRMATION.name

    def get_transaction_hash(self, obj: MultisigConfirmation):
        return obj.ethereum_tx_id


class SafeMultisigTransactionResponseSerializer(SafeMultisigTxSerializerV1):
    safe_tx_hash = Sha3HashField()
    transaction_hash = Sha3HashField(source='ethereum_tx_id')
    submission_date = serializers.DateTimeField(source='created')  # First seen by this service
    is_executed = serializers.BooleanField(source='executed')
    execution_date = serializers.DateTimeField()
    executor = serializers.SerializerMethodField()
    confirmations = serializers.SerializerMethodField()
    signatures = HexadecimalField()

    def get_executor(self, obj: MultisigTransaction) -> Optional[str]:
        if obj.ethereum_tx_id:
            return obj.ethereum_tx._from

    def get_confirmations(self, obj: MultisigTransaction) -> Dict[str, Any]:
        """
        Filters confirmations queryset
        :param obj: MultisigConfirmation instance
        :return: Serialized queryset
        """
        if self.context.get('owners'):
            confirmations = obj.confirmations.filter(owner__in=self.owners, multisig_transaction=obj)
        else:
            confirmations = obj.confirmations

        return SafeMultisigConfirmationResponseSerializer(confirmations, many=True).data


class SafeBalanceResponseSerializer(serializers.Serializer):
    token_address = serializers.CharField()
    balance = serializers.CharField()
