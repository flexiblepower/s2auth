import logging
import hashlib
import hmac
import random
import secrets
import ssl
import string
import httpx
from base64 import b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, OrderedDict

from pydantic import StringConstraints

from wepositive_di import register_provider
from s2auth.common.exceptions import (IncompatibleHmacHashingAlgorithms,
                                      VerificationError)
from s2auth.common.model.s2_connect_pairing import (HmacChallenge,
                                                    HmacHashingAlgorithm)
from s2auth.common.model.s2_connect_common import AccessToken, Deployment


CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits

# Ensure the algorithms are sorted with the most secure/desirable algorithms last.
_ALGORITHM_MAP: OrderedDict[HmacHashingAlgorithm, Callable[..., Any]] = OrderedDict(
    [(HmacHashingAlgorithm.SHA256, hashlib.sha256)]
)


LOGGER = logging.getLogger(__name__)


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


@register_provider()
def generate_access_token() -> AccessToken:
    """Generate a cryptographically secure random access token."""
    return AccessToken(root=b64encode(secrets.token_bytes(32)))


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


def calculate_certificate_fingerprint(cert_der: bytes) -> bytes:
    """Return the SHA-256 fingerprint for a DER-encoded certificate."""
    return hashlib.sha256(cert_der).digest()


def _leaf_certificate_bytes(certificate_bytes: bytes) -> bytes:
    """Return leaf certificate bytes from a cert file payload.

    For PEM chain files this extracts and converts the first certificate block
    (the leaf) to DER bytes. For non-PEM inputs, bytes are returned unchanged.
    """
    pem_begin = b"-----BEGIN CERTIFICATE-----"
    pem_end = b"-----END CERTIFICATE-----"

    begin_index = certificate_bytes.find(pem_begin)
    if begin_index == -1:
        return certificate_bytes

    end_index = certificate_bytes.find(pem_end, begin_index)
    if end_index == -1:
        raise ValueError("Malformed PEM certificate file: missing END CERTIFICATE marker.")
    end_index += len(pem_end)

    leaf_pem_bytes = certificate_bytes[begin_index:end_index]
    try:
        leaf_pem_text = leaf_pem_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Malformed PEM certificate file: non-ASCII certificate block.") from exc

    return ssl.PEM_cert_to_DER_cert(leaf_pem_text)


def calculate_certificate_fingerprint_from_certificate_file(
    certificate_file: str | Path,
) -> bytes:
    """Read a certificate file and return the SHA-256 fingerprint of the leaf certificate."""
    cert_bytes = Path(certificate_file).read_bytes()
    return calculate_certificate_fingerprint(_leaf_certificate_bytes(cert_bytes))


def calculate_fingerprint_from_response_certificate(response: httpx.Response) -> bytes | None:
    network_stream = response.extensions.get("network_stream")
    if network_stream is None:
        return None

    get_extra_info = getattr(network_stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return None

    ssl_object = get_extra_info("ssl_object")
    if ssl_object is None:
        return None

    get_peer_cert = getattr(ssl_object, "getpeercert", None)
    if not callable(get_peer_cert):
        return None

    cert_der = get_peer_cert(binary_form=True)
    if not isinstance(cert_der, (bytes, bytearray)) or not cert_der:
        return None

    return calculate_certificate_fingerprint(bytes(cert_der))

def create_response(pairing_token: str,
                    challenge: HmacChallenge,
                    deployment: str | Deployment,
                    domain_name: str | None,
                    fingerprint: bytes | None,
                    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256) -> bytes:
    try:
        digestmod = _get_hashing_algorithm(algorithm)
    except ValueError as e:
        raise VerificationError(str(e)) from e
    if deployment == Deployment.LAN:
        assert fingerprint is not None
        LOGGER.debug(f"Creating LAN HMAC response with fingerprint: fingerprint=CertificateHash(Sha256({list(fingerprint)}))")
        return hmac_response_lan(pairing_token.encode('utf-8'), challenge.root, fingerprint, digestmod)
    else:
        assert domain_name is not None
        LOGGER.debug(f"Creating WAN HMAC response with domain_name: {domain_name}")
        response =  hmac_response_wan(pairing_token.encode('utf-8'), challenge.root, domain_name, digestmod)
        LOGGER.debug(f"WAN HMAC response: {response}")
        return response


def hmac_response_lan(pairing_token: bytes,
                      challenge: bytes,
                      fingerprint: bytes,
                      digestmod: Callable[..., Any]) -> bytes:
    assert fingerprint is not None, "fingerprint name missing"
    # Lan: R = HMAC(C, pairing_token || fingerprint)
    msg = pairing_token + fingerprint
    return hmac.new(key=challenge, msg=msg, digestmod=digestmod).digest()

def hmac_response_wan(pairing_token: bytes,
                      challenge: bytes,
                      domain_name: str,
                      digestmod: Callable[..., Any]) -> bytes:
    assert domain_name is not None, "Domain name missing"
    # Wan: R = HMAC(C, pairing_token || domain)
    msg = pairing_token + domain_name.encode("utf-8")
    return hmac.new(key=challenge, msg=msg, digestmod=digestmod).digest()


def verify_response(
    pairing_token: str,
    challenge: HmacChallenge,
    response: bytes,
    deployment: str | Deployment,
    domain_name: str | None,
    fingerprint: bytes | None,
    algorithm: HmacHashingAlgorithm = HmacHashingAlgorithm.SHA256,
) -> bool:
    """
    Verify that a received challenge response signature for correctness based on pairing token and algorithm.
    """
    LOGGER.debug(f"pairing_token: {pairing_token}")
    LOGGER.debug(f"challenge: {challenge.root}")
    LOGGER.debug(f"challenge (as str): {b64encode(challenge.root)}")
    LOGGER.debug(f"response: {response}")
    LOGGER.debug(f"algorithm: {algorithm}")

    correct_digest = create_response(pairing_token, challenge, deployment, domain_name, fingerprint, algorithm)
    LOGGER.debug(f"expected response: {correct_digest}")
    if not hmac.compare_digest(correct_digest, response):
        raise VerificationError("Signature is invalid.")
    return True
