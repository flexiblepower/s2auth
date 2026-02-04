import hashlib
import hmac
from base64 import b64decode, b64encode

import pytest

from s2auth.common.exceptions import VerificationError
from s2auth.common.hmac import create_challenge, verify_response


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
