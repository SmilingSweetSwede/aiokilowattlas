import json

import aiohttp
import pytest
from aresponses import Response

from aiokilowattlas import (
    AuthorizationExpired,
    AuthorizationPending,
    KilowattlasAuthError,
    KilowattlasClient,
    KilowattlasConflictError,
    KilowattlasConnectionError,
    KilowattlasRejectedError,
    KilowattlasResponseError,
)
from aiokilowattlas.client import (
    EP_DETAILS,
    EP_DEVICE_CODE,
    EP_DEVICE_TOKEN,
    EP_INGEST,
    EP_ME,
    EP_REVOKE,
)

HOST = "api.kilowattlas.com"


def _json(body, status=200):
    return Response(
        status=status, text=json.dumps(body), content_type="application/json"
    )


def test_base_url_is_normalised():
    client = KilowattlasClient(None, "https://x.example/")  # type: ignore[arg-type]
    assert client.base_url == "https://x.example"


async def test_request_device_code(aresponses, client):
    async def handler(request):
        body = await request.json()
        assert body == {
            "lat": 59.3,
            "lng": 18.1,
            "sample_capability": "realtime_1s",
            "sample_interval_seconds": 1,
        }
        return _json(
            {
                "device_code": "dc",
                "user_code": "ABCD-1234",
                "verification_uri": "https://kilowattlas.com/link",
                "interval": 7,
                "expires_in": 600,
            }
        )

    aresponses.add(HOST, EP_DEVICE_CODE, "POST", handler)
    code = await client.request_device_code(
        59.3, 18.1, {"sample_capability": "realtime_1s", "sample_interval_seconds": 1}
    )
    assert code.device_code == "dc"
    assert code.user_code == "ABCD-1234"
    assert code.interval == 7
    assert code.expires_in == 600
    assert (
        code.verification_uri_complete
        == "https://kilowattlas.com/link?user_code=ABCD-1234"
    )


async def test_request_device_code_defaults_and_minimal_payload(aresponses, client):
    async def handler(request):
        assert await request.json() == {}
        return _json({"device_code": "d", "user_code": "u", "verification_uri": "v"})

    aresponses.add(HOST, EP_DEVICE_CODE, "POST", handler)
    code = await client.request_device_code()
    assert code.interval == 5
    assert code.expires_in == 900


async def test_request_device_code_non_200(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_CODE, "POST", Response(status=503, text="down"))
    with pytest.raises(KilowattlasResponseError, match="503"):
        await client.request_device_code()


async def test_request_device_code_bad_shape(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_CODE, "POST", _json({"user_code": "x"}))
    with pytest.raises(KilowattlasResponseError, match="unexpected"):
        await client.request_device_code()


async def test_non_json_body_is_a_clean_error(aresponses, client):
    aresponses.add(
        HOST,
        EP_DEVICE_CODE,
        "POST",
        Response(status=200, text="<html>oops\nmore</html>"),
    )
    with pytest.raises(KilowattlasResponseError, match="expected JSON") as exc:
        await client.request_device_code()
    assert "\n" not in str(exc.value)


async def test_json_array_body_is_a_clean_error(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_CODE, "POST", _json([1, 2]))
    with pytest.raises(KilowattlasResponseError, match="JSON object"):
        await client.request_device_code()


async def test_connection_error():
    async with aiohttp.ClientSession() as session:
        client = KilowattlasClient(session, "http://127.0.0.1:9")  # nothing listens
        with pytest.raises(KilowattlasConnectionError):
            await client.request_device_code()


async def test_timeout_is_a_connection_error(client, monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            raise TimeoutError

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(client._session, "request", lambda *a, **k: _Ctx())
    with pytest.raises(KilowattlasConnectionError, match="timeout"):
        await client.request_device_code()


async def test_poll_token_success(aresponses, client):
    async def handler(request):
        assert await request.json() == {"device_code": "dc"}
        return _json(
            {"token": "kwc_abc", "site_id": 42, "config": {"config_version": 3}}
        )

    aresponses.add(HOST, EP_DEVICE_TOKEN, "POST", handler)
    grant = await client.poll_token("dc")
    assert grant.token == "kwc_abc"
    assert grant.site_id == 42
    assert grant.config == {"config_version": 3}


async def test_poll_token_without_config(aresponses, client):
    aresponses.add(
        HOST, EP_DEVICE_TOKEN, "POST", _json({"token": "t", "site_id": 1, "config": []})
    )
    grant = await client.poll_token("dc")
    assert grant.config is None


async def test_poll_token_missing_fields(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_TOKEN, "POST", _json({"token": "t"}))
    with pytest.raises(KilowattlasResponseError, match="missing"):
        await client.poll_token("dc")


async def test_poll_token_pending(aresponses, client):
    aresponses.add(
        HOST, EP_DEVICE_TOKEN, "POST", _json({"error": "authorization_pending"}, 400)
    )
    with pytest.raises(AuthorizationPending):
        await client.poll_token("dc")


@pytest.mark.parametrize("err", ["expired_token", "invalid_grant"])
async def test_poll_token_expired(aresponses, client, err):
    aresponses.add(HOST, EP_DEVICE_TOKEN, "POST", _json({"error": err}, 400))
    with pytest.raises(AuthorizationExpired):
        await client.poll_token("dc")


async def test_poll_token_other_error(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_TOKEN, "POST", _json({"error": "weird"}, 400))
    with pytest.raises(KilowattlasResponseError, match="weird"):
        await client.poll_token("dc")


async def test_poll_token_error_without_code(aresponses, client):
    aresponses.add(HOST, EP_DEVICE_TOKEN, "POST", _json({}, 500))
    with pytest.raises(KilowattlasResponseError, match="500"):
        await client.poll_token("dc")


async def test_get_site(aresponses, client):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        return _json(
            {
                "site_id": 5,
                "name": "Roof",
                "capacity_kw": 9.5,
                "config": {"slot_seconds": 900},
            }
        )

    aresponses.add(HOST, EP_ME, "GET", handler)
    site = await client.get_site("tok")
    assert site.site_id == 5
    assert site.name == "Roof"
    assert site.capacity_kw == 9.5
    assert site.config == {"slot_seconds": 900}


async def test_get_site_minimal(aresponses, client):
    aresponses.add(
        HOST, EP_ME, "GET", _json({"site_id": 5, "name": None, "capacity_kw": "n/a"})
    )
    site = await client.get_site("tok")
    assert site.name == ""
    assert site.capacity_kw is None
    assert site.config is None


async def test_get_site_unauthorized(aresponses, client):
    aresponses.add(HOST, EP_ME, "GET", _json({"error": "unauthorized"}, 401))
    with pytest.raises(KilowattlasAuthError):
        await client.get_site("tok")


async def test_get_site_other_status(aresponses, client):
    aresponses.add(HOST, EP_ME, "GET", Response(status=500, text="boom"))
    with pytest.raises(KilowattlasResponseError, match="500"):
        await client.get_site("tok")


async def test_get_site_bad_shape(aresponses, client):
    aresponses.add(HOST, EP_ME, "GET", _json({"name": "x"}))
    with pytest.raises(KilowattlasResponseError, match="unexpected"):
        await client.get_site("tok")


async def test_ingest(aresponses, client):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        body = await request.json()
        assert body == {
            "samples": [{"ts": "2026-10-14T10:00:00.000000Z", "power_kw": 4.2}],
            "measurements": [{"ts": "x", "power_kw": 1, "samples": 3}],
            "donor": {"config_version": 1},
        }
        return _json(
            {
                "accepted": 1,
                "rejected": [
                    {"ts": "x", "reason": "stale"},
                    "garbage",
                    {"reason": "no_ts"},
                ],
                "config": {"config_version": 2},
            }
        )

    aresponses.add(HOST, EP_INGEST, "POST", handler)
    result = await client.ingest(
        "tok",
        samples=[{"ts": "2026-10-14T10:00:00.000000Z", "power_kw": 4.2}],
        measurements=[{"ts": "x", "power_kw": 1, "samples": 3}],
        donor={"config_version": 1},
    )
    assert result.accepted == 1
    assert [(r.ts, r.reason) for r in result.rejected] == [
        ("x", "stale"),
        ("", "no_ts"),
    ]
    assert result.config == {"config_version": 2}


async def test_ingest_tolerates_sparse_response(aresponses, client):
    async def handler(request):
        assert await request.json() == {}
        return _json({"accepted": "many", "rejected": None, "config": 7})

    aresponses.add(HOST, EP_INGEST, "POST", handler)
    result = await client.ingest("tok")
    assert result.accepted == 0
    assert result.rejected == []
    assert result.config is None


async def test_ingest_unauthorized(aresponses, client):
    aresponses.add(HOST, EP_INGEST, "POST", _json({"error": "unauthorized"}, 401))
    with pytest.raises(KilowattlasAuthError):
        await client.ingest("tok", samples=[{"ts": "t", "power_kw": 1}])


async def test_ingest_other_status_truncates_body(aresponses, client):
    aresponses.add(
        HOST, EP_INGEST, "POST", Response(status=500, text="x" * 1000 + "\nline2")
    )
    with pytest.raises(KilowattlasResponseError) as exc:
        await client.ingest("tok", samples=[{"ts": "t", "power_kw": 1}])
    msg = str(exc.value)
    assert "500" in msg
    assert len(msg) < 300
    assert "\n" not in msg


async def test_revoke_ok_and_already_revoked(aresponses, client):
    aresponses.add(HOST, EP_REVOKE, "POST", _json({"status": "revoked"}))
    aresponses.add(HOST, EP_REVOKE, "POST", _json({"error": "unauthorized"}, 401))
    await client.revoke("tok")
    await client.revoke("tok")


async def test_revoke_failure(aresponses, client):
    aresponses.add(HOST, EP_REVOKE, "POST", Response(status=500, text="boom"))
    with pytest.raises(KilowattlasResponseError, match="500"):
        await client.revoke("tok")


async def test_ingest_multi_channel(aresponses, client):
    """0.2.0 wire format: channel declarations, per-channel samples, battery donor."""

    async def handler(request):
        body = await request.json()
        assert body == {
            "channels": [
                {"channel_key": "battery", "measurement_kind": "battery_power"},
                {"channel_key": "battery_soc", "measurement_kind": "battery_soc"},
            ],
            "samples": [
                {"ts": "2026-10-25T10:00:00.000000Z", "power_kw": 3.21},
                {
                    "ts": "2026-10-25T10:00:00.000000Z",
                    "power_kw": -1.5,
                    "channel_key": "battery",
                },
                {
                    "ts": "2026-10-25T10:00:00.000000Z",
                    "power_kw": 101.0,
                    "channel_key": "battery_soc",
                },
            ],
            "donor": {"config_version": 3, "battery_power_kw": 5.0},
        }
        return _json(
            {
                "accepted": 2,
                "rejected": [
                    {
                        "ts": "2026-10-25T10:00:00Z",
                        "channel_key": "battery_soc",
                        "reason": "soc_out_of_range",
                    },
                    {"ts": "2026-10-25T10:00:00Z", "reason": "negative_power"},
                    {"ts": "y", "channel_key": None, "reason": "x"},
                ],
            }
        )

    aresponses.add(HOST, EP_INGEST, "POST", handler)
    result = await client.ingest(
        "tok",
        samples=[
            {"ts": "2026-10-25T10:00:00.000000Z", "power_kw": 3.21},
            {
                "ts": "2026-10-25T10:00:00.000000Z",
                "power_kw": -1.5,
                "channel_key": "battery",
            },
            {
                "ts": "2026-10-25T10:00:00.000000Z",
                "power_kw": 101.0,
                "channel_key": "battery_soc",
            },
        ],
        donor={"config_version": 3, "battery_power_kw": 5.0},
        channels=[
            {"channel_key": "battery", "measurement_kind": "battery_power"},
            {"channel_key": "battery_soc", "measurement_kind": "battery_soc"},
        ],
    )
    assert result.accepted == 2
    assert [(r.channel_key, r.reason) for r in result.rejected] == [
        ("battery_soc", "soc_out_of_range"),
        ("", "negative_power"),
        ("", "x"),
    ]


async def test_ingest_empty_channels_is_legacy_format(aresponses, client):
    """An empty declaration list must not appear on the wire (0.1.0 shape)."""

    async def handler(request):
        assert await request.json() == {"samples": [{"ts": "t", "power_kw": 1}]}
        return _json({"accepted": 1})

    aresponses.add(HOST, EP_INGEST, "POST", handler)
    result = await client.ingest(
        "tok", samples=[{"ts": "t", "power_kw": 1}], channels=[]
    )
    assert result.accepted == 1
    assert result.rejected == []


def test_measurement_kind_constants():
    import aiokilowattlas
    from aiokilowattlas import (
        KIND_BATTERY_POWER,
        KIND_BATTERY_SOC,
        KIND_CONSUMPTION,
        KIND_DEVICE_POWER,
        KIND_EV_CHARGER_POWER,
        KIND_GRID_POWER,
        KIND_GROSS_PRODUCTION,
        KIND_HEAT_PUMP_POWER,
        KIND_NET_EXPORT,
        MEASUREMENT_KINDS,
    )

    assert MEASUREMENT_KINDS == {
        KIND_GROSS_PRODUCTION,
        KIND_NET_EXPORT,
        KIND_CONSUMPTION,
        KIND_BATTERY_POWER,
        KIND_BATTERY_SOC,
        KIND_EV_CHARGER_POWER,
        KIND_HEAT_PUMP_POWER,
        KIND_GRID_POWER,
        KIND_DEVICE_POWER,
    }
    assert MEASUREMENT_KINDS == {
        "gross_production",
        "net_export",
        "grid_power",
        "consumption",
        "battery_power",
        "battery_soc",
        "ev_charger_power",
        "heat_pump_power",
        "device_power",
    }
    assert KIND_BATTERY_SOC == "battery_soc"
    assert KIND_EV_CHARGER_POWER == "ev_charger_power"
    assert KIND_HEAT_PUMP_POWER == "heat_pump_power"
    assert KIND_GRID_POWER == "grid_power"
    assert KIND_DEVICE_POWER == "device_power"
    for name in (
        "KIND_EV_CHARGER_POWER",
        "KIND_HEAT_PUMP_POWER",
        "KIND_GRID_POWER",
        "KIND_DEVICE_POWER",
        "MEASUREMENT_KINDS",
    ):
        assert name in aiokilowattlas.__all__
    assert aiokilowattlas.__version__ == "0.6.0"


def test_default_base_url_honours_env(monkeypatch):
    """KILOWATTLAS_API_BASE redirects the default; blank means production."""
    import importlib

    import aiokilowattlas.client as mod

    monkeypatch.setenv("KILOWATTLAS_API_BASE", " http://backend:8050/ ")
    importlib.reload(mod)
    assert mod.DEFAULT_BASE_URL == "http://backend:8050/"
    assert mod.KilowattlasClient(None).base_url == "http://backend:8050"  # type: ignore[arg-type]

    monkeypatch.setenv("KILOWATTLAS_API_BASE", "   ")
    importlib.reload(mod)
    assert mod.DEFAULT_BASE_URL == mod.PRODUCTION_BASE_URL

    monkeypatch.delenv("KILOWATTLAS_API_BASE")
    importlib.reload(mod)
    assert mod.DEFAULT_BASE_URL == "https://api.kilowattlas.com"


async def test_get_site_details(aresponses, client):
    aresponses.add(
        HOST,
        EP_DETAILS,
        "GET",
        _json({"details": {"install_year": 2021}, "revision": "abc"}),
    )
    got = await client.get_site_details("tok")
    assert got.details == {"install_year": 2021}
    assert got.revision == "abc"


async def test_get_site_details_errors(aresponses, client):
    aresponses.add(HOST, EP_DETAILS, "GET", Response(status=401))
    with pytest.raises(KilowattlasAuthError):
        await client.get_site_details("tok")
    aresponses.add(HOST, EP_DETAILS, "GET", Response(status=500, text="x"))
    with pytest.raises(KilowattlasResponseError):
        await client.get_site_details("tok")
    aresponses.add(HOST, EP_DETAILS, "GET", _json({"details": []}))
    with pytest.raises(KilowattlasResponseError):
        await client.get_site_details("tok")


async def test_update_site_details(aresponses, client):
    async def handler(request):
        assert await request.json() == {
            "revision": "abc",
            "details": {"roof_tilt_deg": 27},
        }
        return _json({"details": {"roof_tilt_deg": 27}, "revision": "def"})

    aresponses.add(HOST, EP_DETAILS, "PUT", handler)
    got = await client.update_site_details("tok", {"roof_tilt_deg": 27}, "abc")
    assert got.revision == "def"


async def test_update_site_details_conflict_and_rejection(aresponses, client):
    aresponses.add(
        HOST,
        EP_DETAILS,
        "PUT",
        Response(
            status=409,
            text=json.dumps({"details": {"install_year": 2022}, "revision": "new"}),
        ),
    )
    with pytest.raises(KilowattlasConflictError) as conflict:
        await client.update_site_details("tok", {}, "old")
    assert conflict.value.current == {"install_year": 2022}
    assert conflict.value.revision == "new"

    aresponses.add(
        HOST,
        EP_DETAILS,
        "PUT",
        Response(status=400, text=json.dumps({"error": "value_out_of_range"})),
    )
    with pytest.raises(KilowattlasRejectedError) as rejected:
        await client.update_site_details("tok", {}, "old")
    assert rejected.value.code == "value_out_of_range"


async def test_update_site_details_other_errors(aresponses, client):
    aresponses.add(HOST, EP_DETAILS, "PUT", Response(status=401))
    with pytest.raises(KilowattlasAuthError):
        await client.update_site_details("tok", {}, "old")
    aresponses.add(HOST, EP_DETAILS, "PUT", Response(status=500, text="x"))
    with pytest.raises(KilowattlasResponseError):
        await client.update_site_details("tok", {}, "old")

