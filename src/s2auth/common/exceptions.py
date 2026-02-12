from typing import ClassVar

from s2auth.common.model.s2_over_ip_pairing import ErrorMessage


class S2PairingError(Exception):
    """Base exception for S2 pairing errors"""

    error_type: ClassVar[ErrorMessage]

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class IncompatibleHmacHashingAlgorithms(S2PairingError):
    """Raised when no common HMAC hashing algorithm is found"""

    error_type: ClassVar[ErrorMessage] = ErrorMessage.IncompatibleHmacHashingAlgorithms


class VerificationError(S2PairingError):
    """Digest verification failed"""

    error_type: ClassVar[ErrorMessage] = (
        ErrorMessage.Other
    )  # TODO should be something else.
