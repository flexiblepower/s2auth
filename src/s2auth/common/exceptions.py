from abc import ABC
from typing import ClassVar, TypeAlias, Union
from s2auth.common.model.s2_connect_pairing import ErrorMessage as PairingErrorType
from s2auth.common.model.s2_connect_connection_init import (
    ErrorMessage as ConnectionErrorType,
)


ErrorType: TypeAlias = Union[PairingErrorType, ConnectionErrorType]


class S2ConnectError(Exception, ABC):
    """Base exception for S2 Connect errors

    Subclasses must define the error_type class attribute.
    """

    error_type: ClassVar[ErrorType]

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class S2ConnectErrorWithDetails(S2ConnectError, ABC):
    """Base exception for S2 Connect errors

    Subclasses must define the error_type class attribute.
    """

    additional_info: str

    def __init__(self, message: str, additional_info: str):
        super().__init__(message)
        self.additional_info = additional_info


class IncompatibleHmacHashingAlgorithms(S2ConnectError):
    """Raised when no common HMAC hashing algorithm is found"""

    error_type = PairingErrorType.IncompatibleHmacHashingAlgorithms


class VerificationError(S2ConnectError):
    """Digest verification failed"""

    error_type = PairingErrorType.Other  # TODO should be something else.


class AccessError(S2ConnectError):
    """Permission is denied to the client. This generally results in an HTTP 401 error."""

    error_type = PairingErrorType.Other  # TODO should be something else.


class PairingNotCompleteError(S2ConnectError):
    """Pairing was not completed successfully before initiating a connection."""

    error_type = ConnectionErrorType.NoLongerPaired  # TODO should be something else.


class InvalidAccessTokenError(AccessError):
    """Invalid AccessToken when authenticating a new s2 connection."""

    error_type = ConnectionErrorType.Other  # TODO should be something else


class InvalidServerError(AccessError):
    """Unknown serverNodeId was specified for this server."""

    error_type = ConnectionErrorType.Other  # TODO should be something else


class NoCompatibleS2ConnectVersionError(S2ConnectErrorWithDetails):
    """No compatible S2Connect versions are available between the client and server."""

    error_type = ConnectionErrorType.Other  # TODO should be something else


class NoCompatibleS2VersionError(S2ConnectErrorWithDetails):
    """No compatible S2 versions are available between the client and server."""

    error_type = ConnectionErrorType.IncompatibleS2MessageVersions


class NoCompatibleCommunitcationProtocol(S2ConnectErrorWithDetails):
    """No compatible communication protocols are available between the client and server."""

    error_type = ConnectionErrorType.IncompatibleCommunicationProtocols
