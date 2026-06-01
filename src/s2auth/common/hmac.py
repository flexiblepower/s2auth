import hashlib
import hmac
import random
import secrets
import string
from base64 import b64encode
from collections.abc import Callable
from typing import Annotated, Any, OrderedDict

from pydantic import StringConstraints

from s2auth.common.dependencies import register_provider
from s2auth.common.exceptions import (IncompatibleHmacHashingAlgorithms,
                                      VerificationError)
from s2auth.common.model.s2_connect_common import AccessToken
from s2auth.common.model.s2_connect_pairing import (HmacChallenge,
                                                    HmacHashingAlgorithm)

CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits

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
    str, StringConstraints(pattern=r"^[A-Za-z0-9+/]{4,}={0,2}$", min_length=4)
]

_ALL_UTF8_CHARS = [chr(i) for i in range(0x110000) if not (0xD800 <= i <= 0xDFFF)]



@register_provider()
def generate_access_token(length: int = 32) -> AccessToken:
    """
    Create the base64 encoded access token (sequence of random bytes) to be sent to the other side of the connection for authentication.

    This function is registered as a dependency provider and can be overridden
    to customize token generation (e.g., static tokens for testing, different lengths, etc.).
    See docs/access_token_override.md for override examples.
    """
    if length < 32:
        raise ValueError("The access token needs to be at least 32 bytes.")
    token = ''.join(random.choice(CHARS) for _ in range(length))
    print(f"Generated access token: {token}")
    return AccessToken(root=b64encode(token.encode("utf-8")))


@register_provider()
def create_pairing_code(s2_node_id: str | None = None, length: int = 9) -> PairingToken:
    """
    Create pairing code, which is [pairing S2 node ID]-[pairing token] if the S2 node id is set otherwise just the token
    """
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token_str = ''.join(random.choice(CHARS) for _ in range(length))

    if s2_node_id:
        return f"{s2_node_id}-{token_str}"
    return token_str


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
    hmac_salt: str,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256
) -> bytes:
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    msg_bin = (pairing_token + hmac_salt).encode("utf-8")
    return hmac.new(key=challenge.root, msg=msg_bin, digestmod=digestmod).digest()


def verify_response(
    pairing_token: str,
    challenge: HmacChallenge,
    response: bytes,
    hmac_salt: str,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
) -> bool:
    """
    Verify that a received challenge response signature for correctness based on pairing token and algorithm.
    """
    print(f"pairing_token: {pairing_token}")
    print(f"challenge: {challenge.root}")
    print(f"challenge (as str): {b64encode(challenge.root)}")
    print(f"response: {response}")
    print(f"response (as str): {b64encode(response)}")
    print(f"algorithm: {algorithm}")
    print(f"hmac_salt: {hmac_salt}")
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    msg_bin = (pairing_token + hmac_salt).encode("utf-8")
    correct_digest = hmac.new(key=challenge.root, msg=msg_bin, digestmod=digestmod).digest()

    print(f"expected response: {correct_digest}")
    print(f"expected response as str: {b64encode(correct_digest)}")
    if not hmac.compare_digest(correct_digest, response):
        raise VerificationError("Signature is invalid.")
    return True
