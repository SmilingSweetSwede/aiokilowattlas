"""Exceptions raised by aiokilowattlas."""

from __future__ import annotations

from typing import Any


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


class KilowattlasConflictError(KilowattlasError):
    """The details changed elsewhere since they were read; `current` has them."""

    def __init__(self, current: dict[str, Any] | None, revision: str | None) -> None:
        """Keep what the server has now, so the caller can show it."""
        super().__init__("details changed since they were read")
        self.current = current
        self.revision = revision


class KilowattlasRejectedError(KilowattlasError):
    """The server refused a value; `code` says why (e.g. value_out_of_range)."""

    def __init__(self, code: str) -> None:
        """Keep the server's reason."""
        super().__init__(code)
        self.code = code
