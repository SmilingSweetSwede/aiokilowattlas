"""Exceptions raised by aiokilowattlas."""


class KilowattlasError(Exception):
    """Base class for every error this library raises."""


class KilowattlasConnectionError(KilowattlasError):
    """The API could not be reached (DNS, TCP, TLS, timeout)."""


class KilowattlasAuthError(KilowattlasError):
    """The bearer token was rejected (revoked, unknown or malformed)."""


class KilowattlasResponseError(KilowattlasError):
    """The API answered, but not with what the contract promises."""


class AuthorizationPending(KilowattlasError):
    """The device code has not been approved on the website yet."""


class AuthorizationExpired(KilowattlasError):
    """The device code expired (or was consumed) before it was approved."""
