import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode
from typing import Annotated, Any, OrderedDict
from collections.abc import Callable

from pydantic import StringConstraints

from s2auth.common.dependencies import register_provider
from s2auth.common.exceptions import VerificationError
from s2auth.common.model.s2_over_ip_pairing import HmacChallenge, HmacHashingAlgorithm

# Ensure the algorithms are sorted with the most secure/desirable algorithms last.
_ALGORITHM_MAP = OrderedDict([(HmacHashingAlgorithm.SHA256, hashlib.sha256)])


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
def create_pairing_token(length: int = 9) -> PairingToken:
    """
    Create the base64 encoded pairing token (sequence of random bytes) to be sent to the other side of the connection.
    The token is a shared secret between the nodes to sign challenges.

    This function is registered as a dependency provider and can be overridden
    to customize token generation (e.g., static tokens for testing, different lengths, etc.).
    See docs/pairing_token_override.md for override examples.
    """
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token = secrets.token_bytes(length)
    return b64encode(token).decode("utf-8")


def random_utf8_string(length: int) -> str:
    return "".join(secrets.choice(_ALL_UTF8_CHARS) for _ in range(length))


def create_challenge(length: int = 128) -> HmacChallenge:
    """
    Create the base64 encoded challenge (sequence of random bytes) to be sent to the other side of the connection.
    The challenge needs to be passed to the the other side of the connection, who should sign it with a shared pairing token.
    verify_response can then be used to verify that signature.
    """
    # if using Base64Bytes for the HmacChallenge rather than Base64Str, use this and remove the random_utf8_string function.
    # challenge_value = secrets.token_bytes(length)
    challenge_value = random_utf8_string(length)
    return HmacChallenge(
        root=b64encode(challenge_value.encode("utf-8")).decode("ascii")
    )


def get_supported_algorithms() -> list[HmacHashingAlgorithm]:
    """Get a list of supported HMAC algorithms."""
    return list(_ALGORITHM_MAP.keys())


def select_algorithm(
    node_algorithms: list[HmacHashingAlgorithm],
) -> HmacHashingAlgorithm:
    supported_algorithms = get_supported_algorithms()
    common = set(supported_algorithms) & set(node_algorithms)

    if not common:
        raise ValueError(
            f"Node does not support any of our algorithms: {get_supported_algorithms()}"
        )

    # Return the last algorithm from supported_algorithms that's in common
    # (later algorithms are preferred as they are typically stronger)
    return [alg for alg in supported_algorithms if alg in common][-1]


def create_response(
    pairing_token: PairingToken,
    challenge: HmacChallenge,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
) -> str:
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    return b64encode(
        hmac.new(
            b64decode(pairing_token),
            msg=challenge.root.encode(
                "utf-8"
            ),  # if using Base64Bytes for the HmacChallenge, remove the .encode()
            digestmod=digestmod,
        ).digest()
    ).decode("ascii")


def verify_response(
    pairing_token: PairingToken,
    challenge: HmacChallenge,
    response: str,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
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
        b64decode(pairing_token),
        msg=challenge.root.encode(
            "utf-8"
        ),  # if using Base64Bytes for the HmacChallenge, remove the .encode()
        digestmod=digestmod,
    ).digest()
    if not hmac.compare_digest(correct_digest, verify_digest):
        raise VerificationError("Signature is invalid.")
    return True
