import aiohttp
import pytest
from aresponses import ResponsesMockServer

from aiokilowattlas import KilowattlasClient

BASE = "https://api.kilowattlas.com"
HOST = "api.kilowattlas.com"


@pytest.fixture
async def aresponses():
    async with ResponsesMockServer() as server:
        yield server


@pytest.fixture
async def client(aresponses):
    async with aiohttp.ClientSession() as session:
        yield KilowattlasClient(session, BASE)
