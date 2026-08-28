# -*- coding: utf-8 -*-
"""Cifrado del data.js para publicarlo en un host publico sin exponer la data.
AES-256-GCM con clave derivada por PBKDF2-HMAC-SHA256 -> interoperable con la
WebCrypto del navegador (crypto.subtle)."""

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERACIONES = 250000


def cifrar(plaintext, password, iteraciones=ITERACIONES):
    """Devuelve un dict {v,iter,salt,iv,ct} con todo en base64, listo para JSON."""
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=iteraciones)
    key = kdf.derive(password.encode("utf-8"))
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)  # ct + tag(16)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"v": 1, "iter": iteraciones, "salt": b(salt), "iv": b(iv), "ct": b(ct)}
