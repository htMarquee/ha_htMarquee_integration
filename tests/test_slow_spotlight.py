"""Spotlight of a movie the device has not cached yet answers slowly.

Reported from a live Home Assistant on 2026-11-24: `POST /api/control/manual` took 16.7 s
for an uncached title (the device downloads metadata and artwork before it answers), the
client gave up at its shared 15 s, and a bare `TimeoutError` reached Home Assistant as a
traceback - while the spotlight appeared on the display a few seconds later.

These run the REAL api client against a real HTTP server on localhost that really takes
that long to answer. Only the two timeout numbers are scaled down (0.3 s and 3 s instead
of 15 s and 60 s) so the test does not take a minute; the slow answer itself is genuine.

    python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant", reason="needs `pip install homeassistant`")

from aiohttp import web  # noqa: E402

from custom_components.htmarquee import api as api_module  # noqa: E402
from custom_components.htmarquee.api import HtMarqueeApi, HtMarqueeApiError  # noqa: E402

# How long the stand-in device takes: longer than the ordinary budget below, well inside
# the spotlight budget - the same relationship as 16.7 s to 15 s and 60 s on a real device.
SLOW_ANSWER_S = 0.8


class SlowDevice:
    """Answers every request correctly, after SLOW_ANSWER_S."""

    def __init__(self) -> None:
        self.port = 0
        self.spotlighted: list[int] = []
        self._runner: web.AppRunner | None = None

    async def _manual(self, request: web.Request) -> web.Response:
        body = await request.json()
        await asyncio.sleep(SLOW_ANSWER_S)  # "caching the movie"
        self.spotlighted.append(body["tmdb_id"])
        return web.json_response({"state": "MANUAL"})

    async def _status(self, request: web.Request) -> web.Response:
        await asyncio.sleep(SLOW_ANSWER_S)
        return web.json_response({"state": "IDLE"})

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/api/control/manual", self._manual)
        app.router.add_get("/api/status", self._status)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()


@pytest.fixture
def scaled_timeouts(monkeypatch):
    monkeypatch.setattr(api_module, "REQUEST_TIMEOUT_S", 0.3)
    monkeypatch.setattr(api_module, "SPOTLIGHT_TIMEOUT_S", 3)


def _run(coro):
    return asyncio.run(coro)


async def _with_device(body):
    device = SlowDevice()
    await device.start()
    client = HtMarqueeApi("127.0.0.1", device.port, use_ssl=False)
    try:
        return await body(device, client)
    finally:
        await client.close()
        await device.stop()


def test_spotlight_waits_for_a_device_that_is_still_caching_the_movie(scaled_timeouts):
    async def body(device, client):
        answer = await client.async_manual(137106)
        return device.spotlighted, answer

    spotlighted, answer = _run(_with_device(body))

    assert spotlighted == [137106]
    assert answer == {"state": "MANUAL"}


def test_an_ordinary_call_that_times_out_is_an_api_error_not_a_bare_timeout(scaled_timeouts):
    """Every caller in the integration catches HtMarqueeApiError. A bare TimeoutError slipped
    past all of them."""
    async def body(device, client):
        with pytest.raises(HtMarqueeApiError) as caught:
            await client._request("GET", "/api/status")
        return str(caught.value)

    message = _run(_with_device(body))

    assert "did not answer within 0.3 s" in message
    assert "/api/status" in message


def test_spotlight_that_outlasts_even_its_own_budget_fails_cleanly(monkeypatch):
    monkeypatch.setattr(api_module, "SPOTLIGHT_TIMEOUT_S", 0.3)

    async def body(device, client):
        with pytest.raises(HtMarqueeApiError, match="did not answer within 0.3 s"):
            await client.async_manual(137106)

    _run(_with_device(body))


def test_the_shipped_budgets_cover_what_was_measured():
    # 16.7 s was measured for an uncached title; the ordinary budget must stay short so a
    # dead device is noticed quickly, and the spotlight budget must clear the measurement.
    assert api_module.REQUEST_TIMEOUT_S == 15
    assert api_module.SPOTLIGHT_TIMEOUT_S >= 30
