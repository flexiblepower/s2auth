import hashlib
import hmac

from s2auth.common.exceptions import VerificationError
from s2auth.common.hmac import (
    PairingToken,
    create_challenge,
    verify_response,
    create_pairing_token,
)
from base64 import b64encode, b64decode
from pydantic import TypeAdapter
import pytest


def test_valid_response():
    """Test that the response is validated correctly."""
    pairing_token = "mypairingtoken"
    digestmod = hashlib.sha256
    challenge = create_challenge()
    signature = b64encode(
        hmac.new(
            pairing_token.encode("utf-8"), msg=b64decode(challenge), digestmod=digestmod
        ).digest()
    ).decode("utf-8")
    assert verify_response(
        pairing_token=pairing_token,
        challenge=challenge,
        response=signature,
        algorithm="SHA256",
    )


def test_invalid_response():
    """Test that verifying the signature with a wrong pairing token raises a VerificationError"""
    pairing_token = "mypairingtoken"
    wrong_pairing_token = "myotherpairingtoken"
    challenge = create_challenge()
    digestmod = hashlib.sha256
    signature = b64encode(
        hmac.new(
            wrong_pairing_token.encode("utf-8"),
            msg=b64decode(challenge),
            digestmod=digestmod,
        ).digest()
    ).decode("utf-8")
    with pytest.raises(VerificationError):
        verify_response(
            pairing_token=pairing_token,
            challenge=challenge,
            response=signature,
            algorithm="SHA256",
        )


def test_invalid_algorithm():
    """Test that specifying an unsupported hashing algorithm raises a VerificationError."""
    pairing_token = "mypairingtoken"
    challenge = create_challenge()
    signature = "random signature"
    invalid_algorithm = "invalid algorithm"
    with pytest.raises(
        VerificationError,
        match=f"Hashing algorithm '{invalid_algorithm}' is not supported",
    ):
        verify_response(
            pairing_token=pairing_token,
            challenge=challenge,
            response=signature,
            algorithm=invalid_algorithm,
        )


def test_create_challenge():
    challenge = create_challenge(length=64)
    assert len(b64decode(challenge)) == 64


def test_create_pairing_token():
    """Test that create_pairing_token returns a valid base64 encoded string."""
    token = create_pairing_token()
    assert isinstance(token, str)
    assert len(token) == 12  # 9 bytes -> 12 characters in base64 (no padding needed)
    # Should be valid base64
    decoded = b64decode(token)
    assert len(decoded) == 9


def test_create_pairing_token_default_length():
    """Test that create_pairing_token with default length returns valid token."""

    token = create_pairing_token()
    assert isinstance(token, str)
    assert len(token) == 12  # 9 bytes -> 12 characters in base64 (no padding needed)

    # Should be valid base64
    decoded = b64decode(token)
    assert len(decoded) == 9

    # Should validate as PairingToken
    adapter = TypeAdapter[str](PairingToken)
    validated = adapter.validate_python(token)
    assert validated == token


def test_create_pairing_token_custom_length():
    """Test that create_pairing_token with custom length returns valid token."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter[str](PairingToken)

    # Test with 10 bytes (will have padding)
    token10 = create_pairing_token(length=10)
    assert len(b64decode(token10)) == 10
    validated10 = adapter.validate_python(token10)
    assert validated10 == token10

    # Test with 12 bytes (no padding)
    token12 = create_pairing_token(length=12)
    assert len(b64decode(token12)) == 12
    validated12 = adapter.validate_python(token12)
    assert validated12 == token12

    # Test with 20 bytes
    token20 = create_pairing_token(length=20)
    assert len(b64decode(token20)) == 20
    validated20 = adapter.validate_python(token20)
    assert validated20 == token20


def test_create_pairing_token_too_short():
    """Test that create_pairing_token raises ValueError for length < 9."""
    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_token(length=8)

    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_token(length=0)

    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_token(length=-1)
