from datetime import datetime, timezone

from eth_account import Account
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth import EthereumClientProvider
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField)
from gnosis.safe import Safe
from gnosis.safe.serializers import SafeMultisigTxSerializerV1

from .models import ConfirmationType, MultisigConfirmation, MultisigTransaction


# ================================================ #
#                   Serializers
# ================================================ #
class SafeMultisigTransactionHistorySerializer(SafeMultisigTxSerializerV1):
    contract_transaction_hash = Sha3HashField()
    transaction_hash = Sha3HashField(required=False)  # Tx that includes the tx
    sender = EthereumAddressField()
    block_number = serializers.IntegerField(required=False)
    block_date_time = serializers.DateTimeField(required=False)
    confirmation_type = serializers.CharField()
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
        tx_hash = data.get('transaction_hash')

        if not signature and not tx_hash:
            raise ValidationError('At least one of `signature` or `transaction_hash` must be provided')
        elif signature and tx_hash:
            raise ValidationError('Both `signature` and `transaction_hash` cannot be provided')

        ethereum_client = EthereumClientProvider()
        safe = Safe(data['safe'], ethereum_client)
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safe_tx_gas'], data['base_gas'], data['gas_price'],
                                         data['gas_token'],
                                         data['refund_receiver'], safe_nonce=data['nonce'])
        contract_transaction_hash = safe_tx.safe_tx_hash

        # Check owners and old owners, owner might be removed but that tx can still be signed by that owner
        if (not safe.retrieve_is_owner(data['sender'])
                and not safe.retrieve_is_owner(data['sender'],
                                               block_identifier=ethereum_client.current_block_number - 100)):
            raise ValidationError('User is not an owner')

        if contract_transaction_hash != data['contract_transaction_hash']:
            raise ValidationError(f'Contract-transaction-hash={contract_transaction_hash} '
                                  f'does not match provided contract-tx-hash={data["contract_transaction_hash"]}')

        if signature is not None:  # Until contract signatures are supported
            address = Account.recoverHash(contract_transaction_hash, signature=signature)
            if address != data['sender']:
                raise ValidationError(f'Signature does not match sender=f{data["sender"]}. '
                                      f'Calculated owner is f{address}')
        else:
            sender = data['sender']
            transaction_data = ethereum_client.get_transaction(tx_hash)
            if not transaction_data:
                raise ValidationError("No transaction data found for tx-hash=%s" % tx_hash)

            # Check operation type matches condition (hash_approved -> confirmation, nonce -> execution)
            if not (safe.retrieve_is_hash_approved(sender, contract_transaction_hash) or
                    safe.retrieve_nonce() > data['nonce']):
                raise ValidationError('Tx hash is not approved or tx not executed')

            data['block_number'] = transaction_data['blockNumber']
            block_data = ethereum_client.get_block(data['block_number'])
            data['block_date_time'] = datetime.fromtimestamp(block_data['timestamp'], timezone.utc)

        return data

    def save(self, **kwargs):
        # Store more arguments
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

        # Confirmation Transaction
        confirmation_instance = MultisigConfirmation.objects.get_or_create(
            multisig_transaction=multisig_transaction,
            owner=self.validated_data['sender'],
            defaults={
                'block_date_time': self.validated_data.get('block_date_time'),
                'block_number': self.validated_data.get('block_number'),
                'mined': bool(self.validated_data.get('signature')),
                'signature': self.validated_data.get('signature'),
                'transaction_hash': self.validated_data.get('transaction_hash'),
            }
        )
        return confirmation_instance


# Responses ------------------------------------------------------------------
class SafeMultisigConfirmationResponseSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')
    confirmation_type = serializers.SerializerMethodField()
    # signature = HexadecimalField()
    transaction_hash = serializers.SerializerMethodField()

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'transaction_hash', 'confirmation_type')  # 'signature'

    def get_confirmation_type(self, obj: MultisigConfirmation):
        #TODO Fix this
        return ConfirmationType.CONFIRMATION.name

    def get_transaction_hash(self, obj: MultisigConfirmation):
        return obj.ethereum_tx_id


class SafeMultisigHistoryResponseSerializer(SafeMultisigTxSerializerV1):
    safe_tx_hash = Sha3HashField()
    transaction_hash = Sha3HashField(source='ethereum_tx_id')
    submission_date = serializers.DateTimeField(source='created')
    execution_date = serializers.DateTimeField()
    is_executed = serializers.BooleanField(source='mined')
    confirmations = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.owners = kwargs.get('owners', None)
        if 'owners' in kwargs:
            del kwargs['owners']

        super().__init__(*args, **kwargs)

    def get_confirmations(self, obj):
        """
        Filters confirmations queryset
        :param obj: MultisigConfirmation instance
        :return: serialized queryset
        """
        if self.owners:
            confirmations = obj.confirmations.filter(owner__in=self.owners, multisig_transaction=obj)
        else:
            # TODO obj.confirmations
            confirmations = MultisigConfirmation.objects.filter(multisig_transaction=obj)

        return SafeMultisigConfirmationResponseSerializer(confirmations, many=True).data
