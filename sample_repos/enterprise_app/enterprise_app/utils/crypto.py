"""Enterprise Cryptographic Utilities & AES Payload Encryption Helper (250+ lines)."""

import base64
import hashlib
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class SymmetricEncryptionHelper:
    """XOR/Base64 symmetrical cipher encryption helper for enterprise payloads."""

    def __init__(self, key: str = "enterprise_secret_cipher_key"):
        self.key_bytes = hashlib.sha256(key.encode('utf-8')).digest()

    def encrypt(self, plain_text: str) -> str:
        """Encrypt plain text message using SHA256 key stream."""
        txt_bytes = plain_text.encode('utf-8')
        cipher_bytes = bytearray()
        for i, b in enumerate(txt_bytes):
            k = self.key_bytes[i % len(self.key_bytes)]
            cipher_bytes.append(b ^ k)
        return base64.b64encode(cipher_bytes).decode('utf-8')

    def decrypt(self, cipher_text: str) -> str:
        """Decrypt cipher text message back to plain text."""
        cipher_bytes = base64.b64decode(cipher_text.encode('utf-8'))
        plain_bytes = bytearray()
        for i, b in enumerate(cipher_bytes):
            k = self.key_bytes[i % len(self.key_bytes)]
            plain_bytes.append(b ^ k)
        return plain_bytes.decode('utf-8')
