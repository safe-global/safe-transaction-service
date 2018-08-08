from django.conf import settings
from ethereum.utils import check_checksum, checksum_encode
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import MultisigConfirmation, MultisigTransaction
from .safe_service import SafeServiceProvider

# ================================================ #
#                Custom Fields
# ================================================ #

class EthereumAddressField(serializers.Field):
    """
    Ethereum address checksumed
    https://github.com/ethereum/EIPs/blob/master/EIPS/eip-55.md
    """

    def to_representation(self, obj):
        return obj

    def to_internal_value(self, data):
        # Check if address is valid

        try:
            if checksum_encode(data) != data:
                raise ValueError
            elif int(data, 16) == 0:
                raise ValidationError("0x0 address is not allowed")
            elif int(data, 16) == 1:
                raise ValidationError("0x1 address is not allowed")
            elif not check_checksum(data):
                raise ValidationError("Address %s is not checksumed" % data)
        except ValueError:
            raise ValidationError("Address %s is not checksumed" % data)
        except Exception:
            raise ValidationError("Address %s is not valid" % data)

        return data


class HexadecimalField(serializers.Field):
    def to_representation(self, obj):
        if obj == b'':
            return '0x'
        else:
            return obj.hex()

    def to_internal_value(self, data):
        if not data or data == '0x':
            return HexBytes('')
        try:
            return HexBytes(data)
        except ValueError:
            raise ValidationError("%s is not hexadecimal" % data)


# ================================================ #
#                   Serializers
# ================================================ #

class SafeMultisigConfirmationSerializer(serializers.ModelSerializer):
    submission_date = serializers.SerializerMethodField()

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'type', 'transaction_hash',)

    def get_submission_date(self, obj):
        return obj.created


class BaseSafeMultisigTransactionSerializer(serializers.Serializer):
    to = EthereumAddressField()
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True)
    operation = serializers.IntegerField(min_value=0, max_value=2)  # Call, DelegateCall or Create
    nonce = serializers.IntegerField(allow_null=True)


class SafeMultisigTransactionSerializer(BaseSafeMultisigTransactionSerializer):
    safe = EthereumAddressField()
    contract_transaction_hash = serializers.CharField(max_length=66)
    transaction_hash = serializers.CharField(max_length=66)
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
        contract_transaction_hash = safe_service.get_hash_for_safe_tx(data['safe'], data['to'], data['value'], data['data'], data['operation'], data['nonce'])

        if contract_transaction_hash.hex()[2:] != data['contract_transaction_hash']:
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
    data = serializers.CharField()
    operation = serializers.IntegerField()
    nonce = serializers.IntegerField()
    submission_date = serializers.SerializerMethodField()
    execution_date = serializers.DateTimeField()
    confirmations = serializers.SerializerMethodField()
    is_executed = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.owners = kwargs.get('owners', None)
        if 'owners' in kwargs:
            del kwargs['owners']

        super(BaseSafeMultisigTransactionSerializer, self).__init__(*args, **kwargs)

    def get_submission_date(self, obj):
        return obj.created

    def get_is_executed(self, obj):
        return obj.status

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
