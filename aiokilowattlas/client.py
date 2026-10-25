"""Thin async client for the Kilowattlas contributed-solar API."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from .exceptions import (
    AuthorizationExpired,
    AuthorizationPending,
    KilowattlasAuthError,
    KilowattlasConnectionError,
    KilowattlasResponseError,
)
from .models import DeviceCode, IngestResult, RejectedSample, SiteInfo, TokenGrant

DEFAULT_BASE_URL = "https://api.kilowattlas.com"

EP_DEVICE_CODE = "/api/v1/contrib/device/code"
EP_DEVICE_TOKEN = "/api/v1/contrib/device/token"
EP_INGEST = "/api/v1/contrib/solar"
EP_REVOKE = "/api/v1/contrib/revoke"
EP_ME = "/api/v1/contrib/me"

# Server text is logged by callers; keep it short and on one line so a hostile
# or broken server cannot spam or inject into a log.
_SNIPPET = 200


def _snippet(text: str) -> str:
    return text[:_SNIPPET].replace("\n", " ")


class KilowattlasClient:
    """Talks to the Kilowattlas contrib endpoints over an injected aiohttp session."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        """Create a client. The session is owned by the caller and never closed here."""
        self._session = session
        self._base = base_url.rstrip("/")

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
            async with self._session.request(
                method, f"{self._base}{path}", json=json_body, headers=headers
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
    ) -> DeviceCode:
        """Start a device-authorization flow.

        `lat`/`lng` are a suggestion for the site's position that the web form
        prefills. `capability` carries optional donor readiness hints
        (sample_capability, sample_interval_seconds, device_brand); the server
        ignores unknown or absent fields.
        """
        payload: dict[str, Any] = {}
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
        data = self._object(text)
        if status == 200:
            if "token" not in data or "site_id" not in data:
                raise KilowattlasResponseError("device/token missing token/site_id")
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
        battery_power_kw).
        `channels` declares the measurement kind of channels that may not exist
        yet, each {channel_key, measurement_kind}; the server applies a
        declaration only when it creates the channel and never relabels an
        existing one. Omitted in the 0.1.0 wire format, which stays valid.
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
