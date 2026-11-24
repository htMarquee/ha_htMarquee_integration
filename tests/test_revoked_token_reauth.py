"""A revoked API token must make Home Assistant ask for a new one.

Found on a live Home Assistant on 2026-11-24. The owner revoked the token the integration
was using; commands and search were refused, but the config entry stayed "loaded", all 25
entities stayed available with frozen values, and no reauth prompt appeared. Cause: the one
call the coordinator treated as mandatory is `/api/status`, which is a PUBLIC endpoint on
the device, and every authenticated call swallowed its errors.

These run the REAL coordinator refresh and the REAL api client against a real HTTP server on
localhost that behaves like the device: `/api/status` answers anyone, everything else checks
the bearer and answers with the device's own 403 text once the token is revoked. The token
is revoked by flipping the server's state, exactly as the owner did in the web app.

    python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("homeassistant", reason="needs `pip install homeassistant`")

from aiohttp import web  # noqa: E402
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError  # noqa: E402

from custom_components.htmarquee.api import HtMarqueeApi  # noqa: E402
from custom_components.htmarquee.coordinator import HtMarqueeCoordinator  # noqa: E402
from custom_components.htmarquee.media_player import HtMarqueeMediaPlayer  # noqa: E402

TOKEN = "htm_goodgoodgoodgoodgoodgoodgoodgood"


class Device:
    """htMarquee 1.6.0's auth behaviour, with a switch to revoke the token."""

    def __init__(self) -> None:
        self.revoked = False
        self.port = 0
        self.calls: list[str] = []
        self._runner: web.AppRunner | None = None

    def _gate(self, request: web.Request) -> web.Response | None:
        self.calls.append(f"{request.method} {request.path}")
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if bearer == TOKEN and not self.revoked:
            return None
        # Verbatim from the device's auth middleware.
        return web.json_response({"detail": "Invalid, expired, or revoked API token"}, status=403)

    async def _status(self, request: web.Request) -> web.Response:
        # PUBLIC on the device: no credential check at all.
        self.calls.append("GET /api/status")
        return web.json_response({"state": "IDLE", "license_tier": "premiere"})

    async def _protected(self, request: web.Request) -> web.Response:
        refused = self._gate(request)
        if refused is not None:
            return refused
        if request.path in ("/api/playlists", "/api/hardware/led/presets",
                            "/api/hardware/led/palettes", "/api/showtimes"):
            return web.json_response([])
        return web.json_response({"version": "1.6.0", "ok": True})

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_route("*", "/{tail:.*}", self._protected)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


def make_coordinator(api: HtMarqueeApi) -> HtMarqueeCoordinator:
    """The real coordinator without Home Assistant's scheduler.

    __init__ only wires up the polling timer, which needs a `hass`. The refresh under
    test (`_async_update_data`) reads and writes the plain attributes set here.
    """
    c = object.__new__(HtMarqueeCoordinator)
    c.api = api
    c.playlists, c.hardware, c.metrics, c.version = [], {}, {}, {}
    c.led_presets, c.led_palettes, c.showtimes = [], [], []
    c.showtimes_supported = None
    c.tier = "matinee"
    c.device_sw_version = None
    c._next_hardware = c._next_playlists = c._next_catalog = 0.0
    c.data = {}
    return c


def run(body: Any) -> Any:
    async def _main() -> Any:
        device = Device()
        await device.start()
        api = HtMarqueeApi("127.0.0.1", device.port, use_ssl=False, token=TOKEN)
        try:
            return await body(device, api)
        finally:
            await api.close()
            await device.stop()

    return asyncio.run(_main())


def test_a_working_token_refreshes_everything():
    async def body(device: Device, api: HtMarqueeApi) -> None:
        coordinator = make_coordinator(api)

        status = await coordinator._async_update_data()

        assert status["state"] == "IDLE"
        assert coordinator.device_sw_version == "1.6.0"

    run(body)


def test_revoking_the_token_starts_reauth_on_the_next_refresh():
    """The live failure. `/api/status` still answers 200, so the refresh used to succeed."""
    async def body(device: Device, api: HtMarqueeApi) -> None:
        coordinator = make_coordinator(api)
        await coordinator._async_update_data()  # healthy first poll

        device.revoked = True  # the owner presses Revoke in the web app
        coordinator._next_hardware = 0.0  # the 30 s hardware group comes due

        with pytest.raises(ConfigEntryAuthFailed, match="revoked API token"):
            await coordinator._async_update_data()

    run(body)


def test_the_poll_after_a_rejection_checks_the_credential_again_at_once():
    """If the group's 30 s deadline were left in the future, the next poll would read only
    the public status endpoint, succeed, and mark the entry healthy again."""
    async def body(device: Device, api: HtMarqueeApi) -> None:
        coordinator = make_coordinator(api)
        await coordinator._async_update_data()
        device.revoked = True
        coordinator._next_hardware = 0.0
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    run(body)


def test_a_command_with_a_revoked_token_is_a_clean_error_and_triggers_a_recheck():
    """Switching playlist was the control that produced an HTTP 500 and a traceback."""
    async def body(device: Device, api: HtMarqueeApi) -> None:
        coordinator = make_coordinator(api)
        await coordinator._async_update_data()
        device.revoked = True

        refreshes: list[bool] = []

        async def request_refresh() -> None:
            refreshes.append(True)

        coordinator.async_request_refresh = request_refresh  # type: ignore[method-assign]
        player = object.__new__(HtMarqueeMediaPlayer)
        player.coordinator = coordinator

        with pytest.raises(HomeAssistantError, match="could not switch the playlist"):
            await player.async_select_source("Auto (Upcoming)")
        with pytest.raises(HomeAssistantError, match="could not skip to the next movie"):
            await player.async_media_next_track()

        # A refused hardware re-read (what LED and TV commands do afterwards) must not
        # raise a raw auth error either; it asks for an immediate poll instead.
        await coordinator.async_refresh_hardware()
        assert refreshes == [True]
        assert coordinator._next_hardware == 0.0

    run(body)
