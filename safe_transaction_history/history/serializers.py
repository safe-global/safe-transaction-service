from datetime import datetime, timezone

from gnosis.eth.django.serializers import EthereumAddressField, Sha3HashField
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe
from gnosis.safe.serializers import SafeMultisigTxSerializer

from .models import HistoryOperation, MultisigConfirmation, MultisigTransaction


# ================================================ #
#                   Serializers
# ================================================ #
class SafeMultisigTransactionHistorySerializer(SafeMultisigTxSerializer):
    contract_transaction_hash = Sha3HashField()
    transaction_hash = Sha3HashField()  # Tx that includes the tx
    sender = EthereumAddressField()
    block_number = serializers.IntegerField(required=False)
    block_date_time = serializers.DateTimeField(required=False)
    type = serializers.CharField()

    def validate_type(self, value: str):
        value = value.upper()
        try:
            return HistoryOperation[value].name
        except KeyError:
            raise ValidationError('History Operation %s not recognized' % value)

    def validate(self, data):
        super().validate(data)

        tx_hash = data['transaction_hash']

        ethereum_client = EthereumClientProvider()
        transaction_data = ethereum_client.get_transaction(tx_hash)

        if not transaction_data:
            raise ValidationError("No transaction data found for tx-hash=%s" % tx_hash)

        tx_block_number = transaction_data['blockNumber']
        block_data = ethereum_client.get_block(tx_block_number)
        tx_block_date_time = datetime.fromtimestamp(block_data['timestamp'], timezone.utc)
        data['block_number'] = tx_block_number
        data['block_date_time'] = tx_block_date_time

        safe = Safe(data['safe'], ethereum_client)
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safe_tx_gas'], data['data_gas'], data['gas_price'], data['gas_token'],
                                         data['refund_receiver'], safe_nonce=data['nonce'])
        contract_transaction_hash = safe_tx.safe_tx_hash

        if contract_transaction_hash != data['contract_transaction_hash']:
            raise ValidationError('contract_transaction_hash does not match provided tx')

        return data

    def save(self, **kwargs):
        # Store more arguments
        multisig_instance, _ = MultisigTransaction.objects.get_or_create(
            safe=self.validated_data['safe'],
            to=self.validated_data['to'],
            value=self.validated_data['value'],
            data=self.validated_data['data'],
            operation=self.validated_data['operation'],
            safe_tx_gas=self.validated_data['safe_tx_gas'],
            data_gas=self.validated_data['data_gas'],
            gas_price=self.validated_data['gas_price'],
            gas_token=self.validated_data['gas_token'],
            refund_receiver=self.validated_data['refund_receiver'],
            nonce=self.validated_data['nonce']
        )

        # Confirmation Transaction
        confirmation_instance = MultisigConfirmation.objects.create(
            block_number=self.validated_data['block_number'],
            block_date_time=self.validated_data['block_date_time'],
            contract_transaction_hash=self.validated_data['contract_transaction_hash'],
            owner=self.validated_data['sender'],
            type=HistoryOperation[self.validated_data['type']].value,
            transaction_hash=self.validated_data['transaction_hash'],
            multisig_transaction=multisig_instance
        )
        return confirmation_instance


class SafeMultisigConfirmationDbSerializer(serializers.ModelSerializer):
    submission_date = serializers.DateTimeField(source='created')
    type = serializers.SerializerMethodField()

    class Meta:
        model = MultisigConfirmation
        fields = ('owner', 'submission_date', 'transaction_hash', 'type')

    def get_type(self, obj):
        return HistoryOperation(obj.type).name


class SafeMultisigHistoryDbSerializer(SafeMultisigTxSerializer):
    submission_date = serializers.DateTimeField(source='created')
    execution_date = serializers.DateTimeField()
    confirmations = serializers.SerializerMethodField()
    is_executed = serializers.BooleanField(source='mined')

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

        return SafeMultisigConfirmationDbSerializer(confirmations, many=True).data
