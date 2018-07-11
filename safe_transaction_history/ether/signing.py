from django.conf import settings
from ethereum import utils


class EthereumSignedMessage:

    def __init__(self, message: str, v: int, r: int, s: int, hash_prefix: str=settings.ETH_HASH_PREFIX):
        """
        :param message: message
        :type message: str
        :param v: v parameter of ethereum signing
        :type v: int
        :param r: r parameter of ethereum signing
        :type r: int
        :param s: s parameter of ethereum signing
        :type s: int
        :param hash_prefix: hash_prefix of the message to avoid injecting transactions or other payloads
        :type hash_prefix: str
        """

        self.hash_prefix = hash_prefix if hash_prefix else ''
        self.message = message
        self.message_hash = self.calculate_hash(message)
        self.v = int(v)
        self.r = int(r)
        self.s = int(s)

    def calculate_hash(self, message: str) -> bytes:
        return utils.sha3(self.hash_prefix + message)

    def check_message_hash(self, message: str) -> bool:
        """
        :param message: message to check if hash matches
        :type message: str
        :return: true if message matches, false otherwise
        :rtype: bool
        """
        return utils.sha3(self.hash_prefix + message) == self.message_hash

    def get_signing_address(self) -> str:
        """
        :return: checksum encoded address starting by 0x, for example `0x568c93675A8dEb121700A6FAdDdfE7DFAb66Ae4A`
        :rtype: str
        """
        encoded_64_address = utils.ecrecover_to_pub(self.message_hash, self.v, self.r, self.s)
        address_bytes = utils.sha3(encoded_64_address)[-20:]
        return utils.checksum_encode(address_bytes)

    def check_signing_address(self, address: str) -> bool:
        """
        :param address: address in any format
        :type address: str
        :return: true if this address was used to sign the message, false otherwise
        :rtype: bool
        """
        return utils.normalize_address(address) == utils.normalize_address(self.get_signing_address())


class EthereumSigner(EthereumSignedMessage):

    def __init__(self, message: str, key: bytes, hash_prefix: str=settings.ETH_HASH_PREFIX):
        """
        :param message: message
        :param key: ethereum key for signing the message
        :param hash_prefix: prefix for hashing
        """
        self.hash_prefix = hash_prefix if hash_prefix else ''
        v, r, s = utils.ecsign(self.calculate_hash(message), key)
        super().__init__(message, v, r, s, hash_prefix=hash_prefix)
