import binascii

from django.core.management.base import BaseCommand
from ...models import SafeMasterCopy

class Command(BaseCommand):
    help = "Insert SafeMasterCopy objects"

    def add_arguments(self, parser):
        parser.add_argument("--address", help="SafeMasterCopy address", required=True)
        parser.add_argument("--initial-block-number", help="Initial block number", required=False, default=0)
        parser.add_argument("--tx-block-number", help="Transaction block number", required=False, default=None)
        parser.add_argument("--safe-version", help="Safe Version", required=False, default="1.3.0")
        parser.add_argument("--l2", help="Address on L2", required=False, default=True)
        parser.add_argument("--deployer", help="Deployer", required=False, default="Gnosis")

    def handle(self, *args, **options):
        mastercopy_address = options["address"]
        initial_block_number = options["initial_block_number"]
        tx_block_number = options["tx_block_number"]
        version = options["safe_version"]
        l2 = options["l2"]
        deployer = options["deployer"]

        # Convert the mastercopy address to binary
        address = self.ethereum_address_to_binary(mastercopy_address)
        
        # Create SafeMasterCopy object
        SafeMasterCopy.objects.create(
            address=address,
            initial_block_number=initial_block_number,
            tx_block_number=tx_block_number,
            version=version,
            l2=l2,
            deployer=deployer,
        )

        self.stdout.write(self.style.SUCCESS(f"Created SafeMasterCopy for {mastercopy_address}"))

    def ethereum_address_to_binary(self, address):
        # Remove the '0x' prefix from the address if it exists
        if address.startswith('0x'):
            address = address[2:]

        # Convert the hexadecimal string to binary representation
        binary_representation = binascii.unhexlify(address)

        return binary_representation