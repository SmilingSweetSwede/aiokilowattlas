# aiokilowattlas

Async Python client for the [Kilowattlas](https://kilowattlas.com) contributed-solar
API. Used by the Home Assistant integration; usable from any asyncio program that
wants to share solar production readings.

```python
import aiohttp
from aiokilowattlas import KilowattlasClient

async with aiohttp.ClientSession() as session:
    client = KilowattlasClient(session)
    code = await client.request_device_code(lat=59.33, lng=18.07)
    print(code.user_code, code.verification_uri)  # show to the user
    grant = await client.poll_token(
        code.device_code
    )  # raises AuthorizationPending until approved
    await client.ingest(
        grant.token, samples=[{"ts": "2026-10-14T10:00:00.000000Z", "power_kw": 4.2}]
    )
```

Several channels per site (0.2.0): declare the kind of any channel that may
not exist yet and tag each sample with its `channel_key`. The server applies a
declaration only when it creates the channel; an existing channel is never
relabelled.

```python
from aiokilowattlas import KIND_BATTERY_POWER, KIND_BATTERY_SOC, KIND_NET_EXPORT

await client.ingest(
    grant.token,
    channels=[
        {"channel_key": "battery", "measurement_kind": KIND_BATTERY_POWER},
        {"channel_key": "grid", "measurement_kind": KIND_NET_EXPORT},
        {"channel_key": "battery_soc", "measurement_kind": KIND_BATTERY_SOC},
    ],
    samples=[
        {"ts": ts, "power_kw": 3.2},  # default: production
        {"ts": ts, "power_kw": -1.5, "channel_key": "battery"},  # + = discharge
        {"ts": ts, "power_kw": 0.9, "channel_key": "grid"},  # + = export
        {"ts": ts, "power_kw": 64.0, "channel_key": "battery_soc"},  # percent
    ],
    donor={"config_version": 3, "battery_power_kw": 5.0},
)
```

Rejected rows carry `channel_key` (empty for the default channel). Battery and
grid kinds are never counted as production by the server.

Endpoints covered: device-code linking (RFC 8628 style), multi-channel
raw-sample ingest, site info (`/contrib/me`) and self-revoke. Server-directed config documents are
validated and clamped by `aiokilowattlas.config.resolve_config`.

MIT licensed.
