"""Exceptions raised by pythermosave."""


class ThermosaveError(Exception):
    """Base exception for pythermosave."""


class ThermosaveConnectionError(ThermosaveError):
    """Raised when Cognito or the ThermoSave API cannot be reached."""


class ThermosaveAuthenticationError(ThermosaveError):
    """Raised when authentication or token refresh fails."""


class ThermosaveInvalidCodeError(ThermosaveAuthenticationError):
    """Raised when an email authentication code is invalid or expired."""


class ThermosaveUnsupportedError(ThermosaveError):
    """Raised when an operation is not defined by the backend API."""


class ThermosaveApiError(ThermosaveError):
    """Raised when Cognito or the ThermoSave API rejects a request."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        """Store the HTTP status and AWS error code of the failed request."""
        super().__init__(message)
        self.status = status
        self.code = code
