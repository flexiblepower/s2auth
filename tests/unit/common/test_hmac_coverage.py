"""Additional coverage tests for HMAC helper branches."""

from base64 import b64encode

import pytest

from s2auth.common.exceptions import VerificationError
from s2auth.common.hmac import (
    _get_hashing_algorithm,  # pyright: ignore[reportPrivateUsage]
    create_challenge,
    create_pairing_code,
    create_response,
    generate_access_token,
    verify_response,
)
from s2auth.common.model.s2_connect_pairing import HmacHashingAlgorithm


def test_get_hashing_algorithm_rejects_unknown_algorithm() -> None:
    with pytest.raises(ValueError, match="not supported"):
        _get_hashing_algorithm("UNKNOWN")  # pyright: ignore[reportArgumentType, reportPrivateUsage]


def test_generate_access_token_returns_base64_token() -> None:
    token = generate_access_token()

    assert len(token.root) == 32


def test_create_pairing_code_returns_token_with_and_without_node_id() -> None:
    token = create_pairing_code(length=9)
    token_with_node = create_pairing_code(s2_node_id="NODE1234", length=9)

    assert len(token) == 9
    assert token_with_node.startswith("NODE1234-")


def test_create_pairing_code_rejects_short_length() -> None:
    with pytest.raises(ValueError, match="at least 9 bytes"):
        create_pairing_code(length=8)


def test_create_response_wraps_unknown_algorithm_as_verification_error() -> None:
    with pytest.raises(VerificationError, match="not supported"):
        create_response(
            pairing_token="pairingToken123",
            challenge=create_challenge(),
            deployment="WAN",
            domain_name="s2.example.com",
            fingerprint=None,
            algorithm="UNKNOWN",  # pyright: ignore[reportArgumentType]
        )


def test_verify_response_wraps_unknown_algorithm_as_verification_error() -> None:
    with pytest.raises(VerificationError, match="not supported"):
        verify_response(
            pairing_token="pairingToken123",
            challenge=create_challenge(),
            response=b64encode(b"response"),
            deployment="WAN",
            domain_name="s2.example.com",
            fingerprint=None,
            algorithm="UNKNOWN",  # pyright: ignore[reportArgumentType]
        )


def test_verify_response_returns_true_for_valid_signature() -> None:
    challenge = create_challenge()
    response = create_response(
        pairing_token="pairingToken123",
        challenge=challenge,
        deployment="WAN",
        domain_name="s2.example.com",
        fingerprint=None,
        algorithm=HmacHashingAlgorithm.SHA256,
    )

    assert verify_response(
        pairing_token="pairingToken123",
        challenge=challenge,
        response=response,
        deployment="WAN",
        domain_name="s2.example.com",
        fingerprint=None,
    )
