import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def fernet_cipher(password, salt):
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=1000,
                     backend=default_backend()).derive(password)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext, password, salt):
    return fernet_cipher(password.encode('utf8'), salt.encode('utf8')).\
            encrypt(plaintext.encode('utf8')).decode('utf8')


def decrypt(ciphertext, password, salt):
    try:
        return fernet_cipher(password.encode('utf8'), salt.encode('utf8')).\
                decrypt(ciphertext.encode('utf8')).decode('utf8')
    except InvalidToken:
        raise ValueError('Invalid ciphertext or password.')
