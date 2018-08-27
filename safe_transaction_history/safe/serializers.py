from django.conf import settings
from ethereum.utils import check_checksum
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from django_eth.serializers import (EthereumAddressField, HexadecimalField,
                                    Sha3HashField)

from .models import MultisigConfirmation, MultisigTransaction
from .safe_service import SafeServiceProvider


# ================================================ #
#                   Serializers
# ================================================ #
class SafeMultisigConfirmationSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'type', 'transaction_hash',)


class BaseSafeMultisigTransactionSerializer(serializers.Serializer):
    to = EthereumAddressField()
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True, allow_blank=True)
    operation = serializers.IntegerField(min_value=0, max_value=2)  # Call, DelegateCall or Create
    nonce = serializers.IntegerField(allow_null=True, min_value=0)


class SafeMultisigTransactionSerializer(BaseSafeMultisigTransactionSerializer):
    safe = EthereumAddressField()
    contract_transaction_hash = Sha3HashField()
    transaction_hash = Sha3HashField()
    sender = EthereumAddressField()
    block_number = serializers.IntegerField()
    block_date_time = serializers.DateTimeField()
    type = serializers.ChoiceField(settings.SAFE_TRANSACTION_TYPES)

    def validate(self, data):
        super().validate(data)

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')
        if 'to' in data and not check_checksum(data['to']):
            raise ValidationError('`to` must be a valid checksumed address')

        if data['operation'] == 2:
            if data['to']:
                raise ValidationError('Operation is Create, but `to` was provided')
        elif not data['to']:
            raise ValidationError('Operation is not create, but `to` was not provided')

        safe_service = SafeServiceProvider()
        # Get contract instance
        safe_contract = safe_service.get_contract(data['safe'])
        # Get safe_tx_typehash value
        safe_tx_typehash = safe_contract.functions.SAFE_TX_TYPEHASH().call().hex()
        # Get the internal contract transaction hash and check if the incoming value is valid
        contract_transaction_hash = safe_service.get_hash_for_safe_tx(safe_tx_typehash, data['safe'],
                                                                      data['to'], data['value'], data['data'],
                                                                      data['operation'], data['nonce'])

        if contract_transaction_hash != data['contract_transaction_hash']:
            raise ValidationError('contract_transaction_hash is not valid')

        return data

    def save(self, **kwargs):
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


class SafeMultisigHistorySerializer(BaseSafeMultisigTransactionSerializer):
    to = serializers.CharField()
    value = serializers.CharField()
    data = HexadecimalField(allow_blank=True, allow_null=True)
    operation = serializers.IntegerField(min_value=0)
    nonce = serializers.IntegerField(min_value=0)
    submission_date = serializers.DateTimeField(source='created')
    execution_date = serializers.DateTimeField()
    confirmations = serializers.SerializerMethodField()
    is_executed = serializers.BooleanField(source='status')

    def __init__(self, *args, **kwargs):
        self.owners = kwargs.get('owners', None)
        if 'owners' in kwargs:
            del kwargs['owners']

        super(BaseSafeMultisigTransactionSerializer, self).__init__(*args, **kwargs)

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
