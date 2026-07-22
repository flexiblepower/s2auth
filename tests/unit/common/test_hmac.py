import hashlib
import hmac
import string
from base64 import b64encode

import pytest
from pydantic import TypeAdapter

from s2auth.common.exceptions import (IncompatibleHmacHashingAlgorithms,
                                      VerificationError)
from s2auth.common.hmac import (PairingToken, create_challenge,
                                create_pairing_code, create_response,
                                get_supported_algorithms, select_algorithm,
                                verify_response)
from s2auth.common.model.s2_connect_pairing import (HmacChallenge,
                                                    HmacHashingAlgorithm)

HMAC_SALT = 's2.example.com'
CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits


class UnsupportedAlgorithm:
    """Test helper for simulating unsupported HMAC algorithms."""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return self.value


def test_invalid_algorithm():
    """Test that specifying an unsupported hashing algorithm raises a VerificationError."""
    pairing_token = "mypairingtoken"
    challenge = create_challenge()
    signature = b"random signature"

    # Create an algorithm object that isn't in the supported list
    invalid_algorithm = UnsupportedAlgorithm("invalid algorithm")

    with pytest.raises(
        VerificationError,
        match="Hashing algorithm .* is not supported",
    ):
        verify_response(
            pairing_token=pairing_token,
            challenge=challenge,
            response=signature,
            hmac_salt=HMAC_SALT,
            algorithm=invalid_algorithm,  # pyright: ignore[reportArgumentType]
        )


def test_create_challenge():
    """Test that create_challenge returns a valid HmacChallenge."""
    challenge = create_challenge(length=64)

    # Should be an HmacChallenge instance
    assert isinstance(challenge, HmacChallenge)

    # challenge.root should be a string
    assert isinstance(challenge.root, bytes)

    # The root should be the decoded random string (length=64)
    assert len(challenge.root) == 64


def test_create_pairing_code_default_length():
    """Test that create_pairing_code with default length returns valid token."""

    token = create_pairing_code()
    assert isinstance(token, str)
    assert len(token) == 9

    assert all(c in CHARS for c in token)

    # Should validate as PairingToken
    adapter = TypeAdapter[str](PairingToken)
    validated = adapter.validate_python(token)
    assert validated == token


def test_create_pairing_code_custom_length():
    """Test that create_pairing_code with custom length returns valid token."""
    adapter = TypeAdapter[str](PairingToken)

    # Test with 10 bytes (will have padding)
    token10 = create_pairing_code(length=10)
    assert len(token10) == 10
    validated10 = adapter.validate_python(token10)
    assert validated10 == token10

    # Test with 12 bytes (no padding)
    token12 = create_pairing_code(length=12)
    assert len(token12) == 12
    validated12 = adapter.validate_python(token12)
    assert validated12 == token12

    # Test with 20 bytes
    token20 = create_pairing_code(length=20)
    assert len(token20) == 20
    validated20 = adapter.validate_python(token20)
    assert validated20 == token20


def test_create_pairing_code_too_short():
    """Test that create_pairing_code raises ValueError for length < 9."""
    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_code(length=8)

    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_code(length=0)

    with pytest.raises(
        ValueError, match="The pairing token needs to be at least 9 bytes"
    ):
        create_pairing_code(length=-1)


def test_create_pairing_code_with_id():
    """Test that create_pairing_code with custom length returns valid token."""
    adapter = TypeAdapter[str](PairingToken)

    # Test with 10 bytes (will have padding)
    pairing_code = create_pairing_code("42", length=10)
    pairing_s2_node_id, token10 = pairing_code.split('-', 1)
    assert len(token10) == 10
    validated10 = adapter.validate_python(token10)
    assert validated10 == token10
    assert pairing_s2_node_id == "42"


def test_create_response_default_algorithm():
    """Test that create_response generates a valid HMAC signature with default algorithm."""
    pairing_token = create_pairing_code()
    challenge = create_challenge()

    response = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)

    # Response should be base64 encoded
    assert isinstance(response, bytes)

    # SHA256 produces 32 bytes
    assert len(response) == 32

    # Manually compute expected HMAC and verify it matches
    msg_bin = (pairing_token + HMAC_SALT).encode("utf-8")
    expected_hmac = hmac.new(
        key=challenge.root,
        msg=msg_bin,
        digestmod=hashlib.sha256
    ).digest()

    assert response == expected_hmac


def test_create_response_invalid_algorithm():
    """Test that create_response raises VerificationError for unsupported algorithm."""
    pairing_token = "mypairingtoken"
    challenge = create_challenge()

    # Create an algorithm object that isn't supported
    invalid_algorithm = UnsupportedAlgorithm("MD5")

    with pytest.raises(
        VerificationError, match="Hashing algorithm .* is not supported"
    ):
        create_response(
            pairing_token,
            challenge,
            algorithm=invalid_algorithm,  # pyright: ignore[reportArgumentType]
            hmac_salt=HMAC_SALT,
        )


def test_create_response_with_different_challenge_lengths():
    """Test create_response works with different challenge lengths."""
    pairing_token = create_pairing_code()

    # Test with 32-byte challenge
    challenge32 = create_challenge(length=32)
    response32 = create_response(pairing_token, challenge32, hmac_salt=HMAC_SALT)
    assert len(response32) == 32

    # Test with 128-byte challenge (default)
    challenge128 = create_challenge(length=128)
    response128 = create_response(pairing_token, challenge128, hmac_salt=HMAC_SALT)
    assert len(response128) == 32

    # Test with 256-byte challenge
    challenge256 = create_challenge(length=256)
    response256 = create_response(pairing_token, challenge256, hmac_salt=HMAC_SALT)
    assert len(response256) == 32

    # Different challenges should produce different responses
    assert response32 != response128
    assert response128 != response256


def test_create_and_verify_response_integration():
    """Integration test: create a response and verify it with the same token."""
    pairing_token = create_pairing_code()
    challenge = create_challenge()

    # Create response
    response = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)

    # Verify response with same token should succeed
    assert verify_response(pairing_token, challenge, response, hmac_salt=HMAC_SALT)


def test_create_and_verify_response_wrong_token():
    """Integration test: verify fails with different pairing token."""
    pairing_token = create_pairing_code()
    wrong_token = create_pairing_code()
    challenge = create_challenge()

    # Create response with first token
    response = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)

    # Verify with different token should fail
    with pytest.raises(VerificationError):
        verify_response(wrong_token, challenge, response, hmac_salt=HMAC_SALT)


def test_create_and_verify_response_wrong_challenge():
    """Integration test: verify fails with different challenge."""
    pairing_token = create_pairing_code()
    challenge1 = create_challenge()
    challenge2 = create_challenge()

    # Create response for first challenge
    response = create_response(pairing_token, challenge1, hmac_salt=HMAC_SALT)

    # Verify with different challenge should fail
    with pytest.raises(VerificationError):
        verify_response(pairing_token, challenge2, response, hmac_salt=HMAC_SALT)


def test_create_response_deterministic():
    """Test that create_response is deterministic for same inputs."""
    pairing_token = create_pairing_code()
    # Create HmacChallenge with UTF-8 safe data
    consistent_data = "consistent_challenge_data_as_text"
    challenge = HmacChallenge(
        root=b64encode(b64encode(consistent_data.encode("utf-8")))
    )

    # Create response multiple times
    response1 = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)
    response2 = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)
    response3 = create_response(pairing_token, challenge, hmac_salt=HMAC_SALT)

    # All responses should be identical
    assert response1 == response2 == response3


def test_select_algorithm_with_matching_algorithm():
    """Test select_algorithm returns the correct algorithm when there's a match."""
    # Should select SHA256 (currently the only/last supported algorithm)
    result = select_algorithm([HmacHashingAlgorithm.SHA256])
    assert result == HmacHashingAlgorithm.SHA256


def test_select_algorithm_no_match():
    """Test select_algorithm raises IncompatibleHmacHashingAlgorithms when no algorithms match."""
    # Create an algorithm object that isn't supported
    unsupported_alg = UnsupportedAlgorithm("UNSUPPORTED")

    with pytest.raises(
        IncompatibleHmacHashingAlgorithms,
        match="Node does not support any of our algorithms",
    ):
        select_algorithm([unsupported_alg])  # pyright: ignore[reportArgumentType]


def test_get_supported_algorithms():
    """Test get_supported_algorithms returns expected algorithms."""
    algorithms = get_supported_algorithms()

    assert isinstance(algorithms, list)
    assert len(algorithms) > 0
    assert HmacHashingAlgorithm.SHA256 in algorithms
