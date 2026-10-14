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

Endpoints covered: device-code linking (RFC 8628 style), raw-sample ingest,
site info (`/contrib/me`) and self-revoke. Server-directed config documents are
validated and clamped by `aiokilowattlas.config.resolve_config`.

MIT licensed.
