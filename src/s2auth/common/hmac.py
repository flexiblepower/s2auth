import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode
from enum import Enum
from typing import Any
from collections.abc import Callable

from s2auth.common.exceptions import VerificationError


class SupportedHashingAlgorithms(Enum):
    SHA256 = hashlib.sha256
    SHA512 = hashlib.sha512

    @classmethod
    def keys(cls) -> list[str]:
        return [i.name for i in cls]


def _get_hashing_algorithm(algorithm: str) -> Callable[..., Any]:
    try:
        return SupportedHashingAlgorithms[algorithm].value
    except KeyError as e:
        raise ValueError(
            f"Hashing algorithm '{algorithm}' is not supported. Please use one of {SupportedHashingAlgorithms.keys()}"
        ) from e


def create_challenge(length: int = 128) -> str:
    """
    Create the base64 encoded challenge (sequence of random bytes) to be sent to the other side of the connection.
    The challenge needs to be passed to the the other side of the connection, who should sign it with a shared pairing token.
    verify_response can then be used to verify that signature.
    """
    challenge_value = secrets.token_bytes(length)
    return b64encode(challenge_value).decode("utf-8")


def verify_response(
    pairing_token: str,
    challenge: str,
    response: str,
    algorithm: str = "SHA256",
) -> bool:
    """
    Verify that a received challenge response signature for correctness based on pairing token and algorithm.
    """
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    verify_digest = b64decode(response)
    correct_digest = hmac.new(
        pairing_token.encode("utf-8"), msg=b64decode(challenge), digestmod=digestmod
    ).digest()
    if not hmac.compare_digest(correct_digest, verify_digest):
        raise VerificationError("Signature is invalid.")
    return True
