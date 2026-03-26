import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode
from typing import Annotated, Any, OrderedDict
from collections.abc import Callable

from pydantic import StringConstraints

from s2auth.common.dependencies import register_provider
from s2auth.common.exceptions import (
    IncompatibleHmacHashingAlgorithms,
    VerificationError,
)
from s2auth.common.model.s2_connect_pairing import HmacChallenge, HmacHashingAlgorithm

# Ensure the algorithms are sorted with the most secure/desirable algorithms last.
_ALGORITHM_MAP: OrderedDict[HmacHashingAlgorithm, Callable[..., Any]] = OrderedDict(
    [(HmacHashingAlgorithm.SHA256, hashlib.sha256)]
)


def _get_hashing_algorithm(algorithm: HmacHashingAlgorithm) -> Callable[..., Any]:
    try:
        return _ALGORITHM_MAP[algorithm]
    except KeyError as e:
        raise ValueError(
            f"Hashing algorithm '{algorithm}' is not supported. Please use one of {get_supported_algorithms()}"
        ) from e


PairingToken = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9+/]{12,}={0,2}$", min_length=12)
]

_ALL_UTF8_CHARS = [chr(i) for i in range(0x110000) if not (0xD800 <= i <= 0xDFFF)]


@register_provider()
def create_pairing_code(s2_node_id: str | None = None, length: int = 9) -> PairingToken:
    """
    Create pairing code, which is [pairing S2 node ID]-[pairing token] if the S2 node id is set otherwise just the token
    """
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token = secrets.token_bytes(length)
    token_str = b64encode(token).decode("utf-8")

    if s2_node_id:
        return f"{s2_node_id}-{token_str}"
    return token_str


def random_utf8_string(length: int) -> str:
    return "".join(secrets.choice(_ALL_UTF8_CHARS) for _ in range(length))


def create_challenge(length: int = 128) -> HmacChallenge:
    """
    Create the base64 encoded challenge (sequence of random bytes) to be sent to the other side of the connection.
    The challenge needs to be passed to the the other side of the connection, who should sign it with a shared pairing token.
    verify_response can then be used to verify that signature.
    """
    challenge_value: bytes = secrets.token_bytes(length)
    return HmacChallenge(root=b64encode(challenge_value))


def get_supported_algorithms() -> list[HmacHashingAlgorithm]:
    """Get a list of supported HMAC algorithms."""
    return list(_ALGORITHM_MAP.keys())


def select_algorithm(
    node_algorithms: list[HmacHashingAlgorithm],
) -> HmacHashingAlgorithm:
    supported_algorithms = get_supported_algorithms()
    common = set(supported_algorithms) & set(node_algorithms)

    if not common:
        raise IncompatibleHmacHashingAlgorithms(
            f"Node does not support any of our algorithms: {get_supported_algorithms()}"
        )

    # Return the last algorithm from supported_algorithms that's in common
    # (later algorithms are preferred as they are typically stronger)
    return [alg for alg in supported_algorithms if alg in common][-1]


def create_response(
    pairing_token: PairingToken,
    challenge: HmacChallenge,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
) -> bytes:
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    return hmac.new(b64decode(pairing_token), msg=challenge.root, digestmod=digestmod).digest()


def verify_response(
    pairing_token: str,
    challenge: HmacChallenge,
    response: bytes,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
) -> bool:
    """
    Verify that a received challenge response signature for correctness based on pairing token and algorithm.
    """
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    correct_digest = hmac.new(b64decode(pairing_token), msg=challenge.root, digestmod=digestmod).digest()

    if not hmac.compare_digest(correct_digest, response):
        raise VerificationError("Signature is invalid.")
    return True
