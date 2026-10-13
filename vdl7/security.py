"""Signing for profile bundles and events (Section 5.4).

The CMS signs with Ed25519; nodes carry the CMS public key in their secure
element and verify before storing anything. Mesh relays forward the original
bytes and signature and never re-sign.

A bench signer (HMAC-SHA256) exists only for hosts without the
`cryptography` package and must be asked for explicitly: it needs a shared
secret, which the spec forbids in the fleet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Protocol

try:  # cryptography is a declared dependency; the guard keeps imports cheap to test
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (Ed25519PrivateKey,
                                                                   Ed25519PublicKey)
    HAVE_ED25519 = True
except Exception:  # pragma: no cover
    HAVE_ED25519 = False


def canonical(obj) -> bytes:
    """Deterministic JSON encoding so signatures are reproducible."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class SignedMessage:
    payload: bytes
    signature: bytes

    def decode(self) -> dict:
        return json.loads(self.payload.decode("utf-8"))

    @property
    def kind(self) -> str:
        return self.decode().get("kind", "")


class Verifier(Protocol):
    def verify(self, data: bytes, signature: bytes) -> bool: ...


class Signer(Protocol):
    def sign(self, data: bytes) -> bytes: ...
    def verify(self, data: bytes, signature: bytes) -> bool: ...
    def sign_obj(self, obj) -> SignedMessage: ...


class _SignerBase:
    def sign_obj(self, obj) -> SignedMessage:
        data = canonical(obj)
        return SignedMessage(data, self.sign(data))  # type: ignore[attr-defined]


class Ed25519Signer(_SignerBase):
    """CMS signing key. `public()` returns the verifier nodes carry."""

    def __init__(self, private_key=None):
        if not HAVE_ED25519:
            raise RuntimeError("Ed25519 needs the 'cryptography' package: pip install cryptography")
        self._key = private_key or Ed25519PrivateKey.generate()
        self._pub = self._key.public_key()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        return Ed25519Verifier(self._pub).verify(data, signature)

    def public(self) -> "Ed25519Verifier":
        return Ed25519Verifier(self._pub)

    # key files ------------------------------------------------------------
    def private_pem(self) -> bytes:
        return self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption())

    @classmethod
    def from_pem(cls, pem: bytes) -> "Ed25519Signer":
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("not an Ed25519 private key")
        return cls(key)


class Ed25519Verifier:
    def __init__(self, public_key):
        self._pub = public_key

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._pub.verify(signature, data)
            return True
        except InvalidSignature:
            return False
        except Exception:
            return False

    def raw(self) -> bytes:
        return self._pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def pem(self) -> bytes:
        return self._pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    @classmethod
    def from_raw(cls, raw: bytes) -> "Ed25519Verifier":
        return cls(Ed25519PublicKey.from_public_bytes(raw))


class DevSigner(_SignerBase):
    """Bench-only HMAC signer. Shared secret: never deploy."""

    def __init__(self, key: bytes | None = None):
        self._key = key or os.urandom(32)

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._key, data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(data), signature)

    def public(self) -> "DevSigner":
        return self


def make_signer(allow_dev: bool = False) -> Signer:
    """Ed25519 signer. Falls back to the HMAC bench signer only when asked."""
    if HAVE_ED25519:
        return Ed25519Signer()
    if allow_dev:
        return DevSigner()
    raise RuntimeError("Ed25519 needs the 'cryptography' package: pip install cryptography")
