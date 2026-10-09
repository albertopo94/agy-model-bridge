"""Centralized exception hierarchy for agy-model-bridge."""


class BridgeError(Exception):
    """Base exception for all agy-model-bridge errors."""

    pass


class AuthenticationError(BridgeError):
    """Raised when authentication fails (Keychain, local API key, or upstream token)."""

    pass


class ForbiddenError(BridgeError):
    """Raised on 403 Forbidden / permission denied."""

    pass


class InvalidRequestError(BridgeError):
    """Raised on 400 Bad Request / malformed payload."""

    pass


class ModelNotFoundError(BridgeError):
    """Raised on 404 Model Not Found."""

    pass


class RateLimitError(BridgeError):
    """Raised on 429 Too Many Requests."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CapacityExhaustedError(BridgeError):
    """Raised on 503 Service Unavailable / capacity exhausted."""

    pass


class UpstreamTimeoutError(BridgeError):
    """Raised on upstream connection or read timeouts."""

    pass


class UpstreamError(BridgeError):
    """Raised when upstream API returns an unhandled error status."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProtocolError(BridgeError):
    """Raised when protocol translation or formatting fails."""

    pass
