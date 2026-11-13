"""Thin async client for the Kilowattlas contributed-solar API."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .exceptions import (
    AuthorizationExpired,
    AuthorizationPending,
    KilowattlasAuthError,
    KilowattlasConfigError,
    KilowattlasConflictError,
    KilowattlasConnectionError,
    KilowattlasRejectedError,
    KilowattlasResponseError,
)
from .models import (
    DeviceCode,
    IngestResult,
    RejectedSample,
    SiteDetails,
    SiteInfo,
    TokenGrant,
)

PRODUCTION_BASE_URL = "https://api.kilowattlas.com"

# Developers and self-hosters point the client at another server with
# KILOWATTLAS_API_BASE (the Kilowattlas dev stack sets http://backend:8050 for
# its Home Assistant test container). Read once at import: Home Assistant
# constructs the client without a base_url, so this is the only knob it has.
DEFAULT_BASE_URL = (
    os.environ.get("KILOWATTLAS_API_BASE", "").strip() or PRODUCTION_BASE_URL
)

EP_DEVICE_CODE = "/api/v1/contrib/device/code"
EP_DEVICE_TOKEN = "/api/v1/contrib/device/token"
EP_DEVICE_ACTIVATE = "/api/v1/contrib/device/activate"
EP_INGEST = "/api/v1/contrib/solar"
EP_REVOKE = "/api/v1/contrib/revoke"
EP_ME = "/api/v1/contrib/me"
EP_DETAILS = "/api/v1/contrib/me/details"

# Server text is logged by callers; keep it short and on one line so a hostile
# or broken server cannot spam or inject into a log.
_SNIPPET = 200


# No call here is slow by design. Without a limit of its own, a request that
# hangs sits for the session's timeout, which in Home Assistant is five minutes.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _snippet(text: str) -> str:
    return text[:_SNIPPET].replace("\n", " ")


# Where plain HTTP is accepted: this machine and private networks, spelled out
# so the answer does not shift with the Python version (`ipaddress.is_private`
# also covers reserved and documentation ranges, and has changed over time).
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",  # carrier-grade NAT range, used by overlay networks
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)
# Names that only resolve on a local network or machine.
_LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".localhost", ".home.arpa")
# A single label that starts with a letter: `localhost`, a Docker service name.
# A label of digits or `0x...` is not a name but another way to write an
# address (`http://134744072` is 8.8.8.8), so it must not pass as one.
_LOCAL_NAME = re.compile(r"[a-z][a-z0-9-]*")


def _is_local(host: str) -> bool:
    """Whether `host` is on this machine or network and cannot be a public one."""
    try:
        address = ipaddress.ip_address(host.partition("%")[0])
    except ValueError:
        return bool(_LOCAL_NAME.fullmatch(host)) or (
            host.endswith(_LOCAL_SUFFIXES)
            and all(_LOCAL_NAME.fullmatch(label) for label in host.split("."))
        )
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return any(address in net for net in _LOCAL_NETWORKS if net.version == address.version)


def checked_base_url(base_url: str) -> str:
    """Return `base_url` without a trailing slash, or refuse it.

    The bearer token and every reading travel to this address, so it must be
    HTTPS. Plain HTTP is accepted only for a development stack on the local
    machine or network (see `_is_local`), never for a host on the internet.
    The address is a scheme, a host and optionally a port and a path: one
    with credentials, a query or a fragment is refused as well.

    Raises KilowattlasConfigError, which is both a KilowattlasError and a
    ValueError.
    """
    refusal = KilowattlasConfigError(
        f"refusing API base {base_url!r}: it must be https "
        "(http is accepted only for a local development host)"
    )
    try:
        url = urlsplit(base_url)
        url.port  # noqa: B018 - reading it validates the port
    except ValueError:
        raise refusal from None
    host = (url.hostname or "").lower()
    if (
        not host
        or not host.isascii()
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise refusal
    if url.scheme == "https" or (url.scheme == "http" and _is_local(host)):
        return base_url.rstrip("/")
    raise refusal


class KilowattlasClient:
    """Talks to the Kilowattlas contrib endpoints over an injected aiohttp session."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        """Create a client. The session is owned by the caller and never closed here.

        Raises KilowattlasConfigError (also a ValueError) for a base URL that
        is not HTTPS (see `checked_base_url`).
        """
        self._session = session
        self._base = checked_base_url(base_url)

    @property
    def base_url(self) -> str:
        """The API base this client talks to."""
        return self._base

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> tuple[int, str]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            # The API never redirects. Following one would hand the request,
            # and on the same host the token, to wherever it points.
            async with self._session.request(
                method,
                f"{self._base}{path}",
                json=json_body,
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                return resp.status, await resp.text()
        except aiohttp.ClientError as err:
            raise KilowattlasConnectionError(
                f"cannot reach {self._base}: {err}"
            ) from err
        except TimeoutError as err:
            raise KilowattlasConnectionError(
                f"timeout talking to {self._base}"
            ) from err

    @staticmethod
    def _object(text: str) -> dict[str, Any]:
        try:
            data = json.loads(text)
        except ValueError as err:
            raise KilowattlasResponseError(
                f"expected JSON from the API but got: {_snippet(text)!r}"
            ) from err
        if not isinstance(data, dict):
            raise KilowattlasResponseError("expected a JSON object from the API")
        return data

    # --- device linking ---------------------------------------------------------

    async def request_device_code(
        self,
        lat: float | None = None,
        lng: float | None = None,
        capability: dict[str, Any] | None = None,
        *,
        activation: bool = False,
    ) -> DeviceCode:
        """Start a device-authorization flow.

        `lat`/`lng` are a suggestion for the site's position that the web form
        prefills. `capability` carries optional donor readiness hints
        (sample_capability, sample_interval_seconds, device_brand); the server
        ignores unknown or absent fields.

        With `activation=True` the installation is not created when the user
        approves, but when the caller reports that its own setup is finished
        (`activate`). A setup abandoned before that leaves nothing behind. The
        grant from `poll_token` then says `activation_required`; a server that
        predates this ignores the request and answers as before.
        """
        payload: dict[str, Any] = {}
        if activation:
            payload["activation"] = True
        if lat is not None:
            payload["lat"] = lat
        if lng is not None:
            payload["lng"] = lng
        if capability:
            payload.update(capability)
        status, text = await self._request("POST", EP_DEVICE_CODE, json_body=payload)
        if status != 200:
            raise KilowattlasResponseError(f"device/code returned {status}")
        data = self._object(text)
        if not all(k in data for k in ("device_code", "user_code", "verification_uri")):
            raise KilowattlasResponseError(
                "device/code returned an unexpected response"
            )
        return DeviceCode(
            device_code=str(data["device_code"]),
            user_code=str(data["user_code"]),
            verification_uri=str(data["verification_uri"]),
            interval=int(data.get("interval", 5)),
            expires_in=int(data.get("expires_in", 900)),
        )

    async def poll_token(self, device_code: str) -> TokenGrant:
        """Exchange an approved device code for the ingest token.

        Raises AuthorizationPending while the user has not approved yet, and
        AuthorizationExpired once the code is dead.
        """
        status, text = await self._request(
            "POST", EP_DEVICE_TOKEN, json_body={"device_code": device_code}
        )
        try:
            data = self._object(text)
        except KilowattlasResponseError:
            if status == 200:
                raise
            # An answer that is no JSON at all (a redirect, a proxy's error
            # page): its status says more than its body.
            raise KilowattlasResponseError(
                f"device/token returned {status}"
            ) from None
        if status == 200:
            if "token" not in data:
                raise KilowattlasResponseError("device/token missing token")
            if data.get("activation_required") is True:
                return TokenGrant(token=str(data["token"]), activation_required=True)
            if "site_id" not in data:
                raise KilowattlasResponseError("device/token missing site_id")
            config = data.get("config")
            return TokenGrant(
                token=str(data["token"]),
                site_id=int(data["site_id"]),
                config=config if isinstance(config, dict) else None,
            )
        err = str(data.get("error", ""))
        if err == "authorization_pending":
            raise AuthorizationPending
        if err in ("expired_token", "invalid_grant"):
            raise AuthorizationExpired
        raise KilowattlasResponseError(f"device/token error: {err or status}")

    async def activate(self, token: str) -> SiteInfo:
        """Report that setup is finished: the approved installation is created.

        The last step after a grant with `activation_required`. Repeating it
        answers the same, so it is safe to call again after a lost answer.

        Raises AuthorizationExpired when the approval ran out before this call
        (nothing was created), KilowattlasAuthError when the token is unknown,
        and KilowattlasRejectedError when the server can no longer create what
        was approved (for example the chosen plant got another integration
        meanwhile).
        """
        status, text = await self._request("POST", EP_DEVICE_ACTIVATE, token=token)
        if status == 401:
            raise KilowattlasAuthError("token rejected")
        if status == 410:
            raise AuthorizationExpired
        if status in (400, 403, 409):
            raise KilowattlasRejectedError(
                str(self._object(text).get("error") or "invalid_request")
            )
        if status != 200:
            raise KilowattlasResponseError(
                f"device/activate returned {status}: {_snippet(text)}"
            )
        data = self._object(text)
        if "site_id" not in data:
            raise KilowattlasResponseError(
                "device/activate returned an unexpected response"
            )
        config = data.get("config")
        return SiteInfo(
            site_id=int(data["site_id"]),
            name="",
            config=config if isinstance(config, dict) else None,
        )

    # --- token-authed -----------------------------------------------------------

    async def get_site(self, token: str) -> SiteInfo:
        """Describe the site the token belongs to; validates the token for free.

        Raises KilowattlasAuthError when the token is revoked or unknown.
        """
        status, text = await self._request("GET", EP_ME, token=token)
        if status == 401:
            raise KilowattlasAuthError("token rejected")
        if status != 200:
            raise KilowattlasResponseError(f"me returned {status}: {_snippet(text)}")
        data = self._object(text)
        if "site_id" not in data:
            raise KilowattlasResponseError("me returned an unexpected response")
        capacity = data.get("capacity_kw")
        config = data.get("config")
        return SiteInfo(
            site_id=int(data["site_id"]),
            name=str(data.get("name") or ""),
            capacity_kw=float(capacity) if isinstance(capacity, int | float) else None,
            config=config if isinstance(config, dict) else None,
        )

    async def get_site_details(self, token: str) -> SiteDetails:
        """Read the owner's description of the installation."""
        status, text = await self._request("GET", EP_DETAILS, token=token)
        if status == 401:
            raise KilowattlasAuthError("token rejected")
        if status != 200:
            raise KilowattlasResponseError(
                f"details returned {status}: {_snippet(text)}"
            )
        return self._site_details(text)

    async def update_site_details(
        self, token: str, details: dict[str, Any], revision: str
    ) -> SiteDetails:
        """Replace the description, based on the revision last read.

        Raises KilowattlasConflictError when it changed elsewhere in between,
        and KilowattlasRejectedError when the server refuses a value.
        """
        status, text = await self._request(
            "PUT",
            EP_DETAILS,
            json_body={"revision": revision, "details": details},
            token=token,
        )
        if status == 401:
            raise KilowattlasAuthError("token rejected")
        if status == 409:
            data = self._object(text)
            current = data.get("details")
            raise KilowattlasConflictError(
                current if isinstance(current, dict) else None,
                str(data["revision"]) if data.get("revision") else None,
            )
        if status == 400:
            raise KilowattlasRejectedError(
                str(self._object(text).get("error") or "invalid_request")
            )
        if status != 200:
            raise KilowattlasResponseError(
                f"details returned {status}: {_snippet(text)}"
            )
        return self._site_details(text)

    def _site_details(self, text: str) -> SiteDetails:
        data = self._object(text)
        details = data.get("details")
        revision = data.get("revision")
        if not isinstance(details, dict) or not revision:
            raise KilowattlasResponseError("details returned an unexpected response")
        return SiteDetails(details=details, revision=str(revision))

    async def ingest(
        self,
        token: str,
        samples: list[dict[str, Any]] | None = None,
        measurements: list[dict[str, Any]] | None = None,
        donor: dict[str, Any] | None = None,
        channels: list[dict[str, Any]] | None = None,
    ) -> IngestResult:
        """Push readings. Idempotent server-side.

        `samples` are raw readings at whatever resolution the source produces,
        each {ts, power_kw, channel_key?}; the server computes slot means. For a
        `battery_soc` channel `power_kw` carries percent (0-100), not kW.
        `measurements` are pre-aggregated slot means (legacy shape).
        `donor` is optional self-reported telemetry
        (config_version, measured_sample_interval_seconds, sample_capability,
        battery_power_kw, and since 0.5.0 battery_capacity_kwh).
        `channels` declares the measurement kind of channels that may not exist
        yet, each {channel_key, measurement_kind, name?}; the server applies a
        declaration only when it creates the channel and never relabels an
        existing one. Omitted in the 0.1.0 wire format, which stays valid.
        Kinds: gross_production, net_export, consumption, battery_power,
        battery_soc; since 0.3.0 the loads ev_charger_power and heat_pump_power
        (kW, never negative, never counted as production); since 0.5.0
        grid_power (the Home Assistant Energy dashboard's sign, positive =
        import, stored as net_export) and device_power (one named device).
        """
        body: dict[str, Any] = {}
        if channels:
            body["channels"] = channels
        if samples:
            body["samples"] = samples
        if measurements:
            body["measurements"] = measurements
        if donor:
            body["donor"] = donor
        status, text = await self._request(
            "POST", EP_INGEST, json_body=body, token=token
        )
        if status == 401:
            raise KilowattlasAuthError("token rejected")
        if status != 200:
            raise KilowattlasResponseError(
                f"ingest returned {status}: {_snippet(text)}"
            )
        data = self._object(text)
        rejected = [
            RejectedSample(
                ts=str(r.get("ts", "")),
                reason=str(r.get("reason", "?")),
                channel_key=str(r.get("channel_key") or ""),
            )
            for r in (data.get("rejected") or [])
            if isinstance(r, dict)
        ]
        config = data.get("config")
        try:
            accepted = int(data.get("accepted", 0))
        except (TypeError, ValueError):
            accepted = 0
        return IngestResult(
            accepted=accepted,
            rejected=rejected,
            config=config if isinstance(config, dict) else None,
        )

    async def revoke(self, token: str) -> None:
        """Disable this token's site server-side. A 401 (already revoked) is success."""
        status, text = await self._request("POST", EP_REVOKE, token=token)
        if status not in (200, 401):
            raise KilowattlasResponseError(
                f"revoke returned {status}: {_snippet(text)}"
            )
