from django.conf import settings
from django_eth.serializers import (EthereumAddressField, HexadecimalField,
                                    Sha3HashField)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.safe.safe_service import SafeService
from gnosis.safe.serializers import (SafeMultisigEstimateTxSerializer,
                                     SafeMultisigTxSerializer)

from .models import MultisigConfirmation, MultisigTransaction


# ================================================ #
#                   Serializers
# ================================================ #
class SafeMultisigConfirmationSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'type', 'transaction_hash',)


class SafeMultisigTransactionHistorySerializer(SafeMultisigTxSerializer):
    contract_transaction_hash = Sha3HashField()
    transaction_hash = Sha3HashField()  # Tx that includes the tx
    sender = EthereumAddressField()
    block_number = serializers.IntegerField()
    block_date_time = serializers.DateTimeField()
    type = serializers.ChoiceField(settings.SAFE_TRANSACTION_TYPES)

    def validate(self, data):
        super().validate(data)

        contract_transaction_hash = SafeService.get_hash_for_safe_tx(data['safe'], data['to'], data['value'],
                                                                     data['data'], data['operation'],
                                                                     data['safe_tx_gas'], data['data_gas'],
                                                                     data['gas_price'], data['gas_token'],
                                                                     data['refund_receiver'],
                                                                     data['nonce'])

        if contract_transaction_hash != data['contract_transaction_hash']:
            raise ValidationError('contract_transaction_hash is not valid')

        return data

    def save(self, **kwargs):
        # Store more arguments
        multisig_instance, _ = MultisigTransaction.objects.get_or_create(
            safe=self.validated_data['safe'],
            to=self.validated_data['to'],
            value=self.validated_data['value'],
            data=self.validated_data['data'],
            operation=self.validated_data['operation'],
            nonce=self.validated_data['nonce']
        )

        # Confirmation Transaction
        confirmation_instance = MultisigConfirmation.objects.create(
            block_number=self.validated_data['block_number'],
            block_date_time=self.validated_data['block_date_time'],
            contract_transaction_hash=self.validated_data['contract_transaction_hash'],
            owner=self.validated_data['sender'],
            type=self.validated_data['type'],
            transaction_hash=self.validated_data['transaction_hash'],
            multisig_transaction=multisig_instance
        )
        return confirmation_instance


class SafeMultisigHistoryDbSerializer(SafeMultisigEstimateTxSerializer):
    nonce = serializers.IntegerField(min_value=0)
    submission_date = serializers.DateTimeField(source='created')
    execution_date = serializers.DateTimeField()
    confirmations = serializers.SerializerMethodField()
    is_executed = serializers.BooleanField(source='status')

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
            confirmations = MultisigConfirmation.objects.filter(owner__in=self.owners, multisig_transaction=obj.id)
        else:
            confirmations = MultisigConfirmation.objects.filter(multisig_transaction=obj.id)

        return SafeMultisigConfirmationSerializer(confirmations, many=True).data
