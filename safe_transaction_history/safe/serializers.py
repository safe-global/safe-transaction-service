from ethereum.utils import checksum_encode
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from hexbytes import HexBytes

from safe_transaction_history.ether.signing import calculate_hex_hash
from .models import MultisigTransaction, MultisigConfirmation


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
    owner = EthereumAddressField()
    submission_date = serializers.SerializerMethodField()

    class Mera:
        model = MultisigConfirmation

    def get_submission_date(self, obj):
        return obj.created


class BaseSafeMultisigTransactionSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    to = EthereumAddressField()
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True)
    operation = serializers.IntegerField(min_value=0, max_value=2)  # Call, DelegateCall or Create
    contract_transaction_hash = serializers.CharField()
    nonce = serializers.IntegerField(allow_null=True)
    sender = EthereumAddressField()

    def validate(self, data):
        super().validate(data)

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')

        if data['operation'] == 2:
            if data['to']:
                raise ValidationError('Operation is Create, but `to` was provided')
        elif not data['to']:
            raise ValidationError('Operation is not create, but `to` was not provided')

        # TODO Review
        # check if transaction hash is correct
        message = {
            'from': data['sender'],
            'to': data['to'],
            'value': data['value'],
            'data': data['data'],
            'nonce': data['nonce']
        }

        transaction_hash = calculate_hex_hash(message)

        if transaction_hash != data['contract_transaction_hash']:
            raise ValidationError('contract_transaction_hash is not valid')

        return data

    def save(self, **kwargs):
        instance = MultisigTransaction.objects.create(
            safe=self.validated_data['safe'],
            to=self.validated_data['to'],
            value=self.validated_data['value'],
            data=self.validated_data['data'],
            operation=self.validated_data['operation'],
            nonce=self.validated_data['nonce']
        )
        return instance


class SafeMultisigHistorySerializer(BaseSafeMultisigTransactionSerializer):
    confirmations = SafeMultisigConfirmationSerializer(many=True)

    def to_internal_value(self, data):
        pass
