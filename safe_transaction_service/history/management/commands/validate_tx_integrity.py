from django.core.management.base import BaseCommand
from django.db import connection

from hexbytes import HexBytes
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.safe import Safe
from safe_eth.safe.safe_signature import SafeSignature

from ...models import MultisigConfirmation, MultisigTransaction


class Command(BaseCommand):
    help = "Validate multisig transaction integrity for multisig transaction in queue"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ethereum_client = get_auto_ethereum_client()

    def get_queue_for_every_safe(self) -> list[bytes]:
        """
        :return: Pending safes to execute
        """
        query = (
            "SELECT ENCODE(safe_tx_hash, 'hex') FROM history_multisigtransaction hm "
            "JOIN history_safelaststatus hs "
            "ON hm.safe = hs.address AND hm.nonce >= hs.nonce AND hm.ethereum_tx_id is NULL"
        )
        with connection.cursor() as cursor:
            # Queries all the ERC721 IN and all OUT and only returns the ones currently owned
            cursor.execute(query, [])
            return [HexBytes(safe_tx_hash) for (safe_tx_hash,) in cursor.fetchall()]

    def get_multisig_transactions(
        self, safe_tx_hash: list[bytes]
    ) -> list[MultisigTransaction]:
        return MultisigTransaction.objects.filter(
            safe_tx_hash__in=safe_tx_hash
        ).iterator()

    def validate_safe_tx_hash(self, multisig_transaction: MultisigTransaction) -> bool:
        """
        :param multisig_transaction:
        :return: `True` if database safe_tx_hash matches the calculated one, `False` otherwise
        """
        safe = Safe(multisig_transaction.safe, self.ethereum_client)
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
        return HexBytes(multisig_transaction.safe_tx_hash) == safe_tx.safe_tx_hash

    def validate_confirmation(
        self,
        multisig_confirmation: MultisigConfirmation,
        multisig_transaction: MultisigTransaction,
    ) -> bool:
        """
        :param multisig_confirmation:
        :param multisig_transaction:
        :return: `True` if database confirmation owner matches the calculated one from the signature, `False` otherwise
        """
        for safe_signature in SafeSignature.parse_signature(
            multisig_confirmation.signature, multisig_transaction.safe_tx_hash
        ):
            return (
                safe_signature.is_valid(self.ethereum_client, multisig_transaction.safe)
                and safe_signature.owner == multisig_confirmation.owner
            )

    def handle(self, *args, **options):
        safe_tx_hashes = self.get_queue_for_every_safe()
        self.stdout.write(
            self.style.SUCCESS(f"Found {len(safe_tx_hashes)} transactions")
        )

        for multisig_transaction in self.get_multisig_transactions(safe_tx_hashes):
            if multisig_transaction.signatures:
                self.stdout.write(
                    self.style.WARNING(
                        f"{multisig_transaction.safe_tx_hash} should not have signatures as it is not executed"
                    )
                )
            if not self.validate_safe_tx_hash(multisig_transaction):
                self.stdout.write(
                    self.style.WARNING(
                        f"{multisig_transaction.safe_tx_hash} is not matching"
                    )
                )

            for multisig_confirmation in multisig_transaction.confirmations.all():
                if not self.validate_confirmation(
                    multisig_confirmation, multisig_transaction
                ):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Confirmation for owner {multisig_confirmation.owner} is not valid "
                            f"for multisig transaction {multisig_transaction.safe_tx_hash}"
                        )
                    )
