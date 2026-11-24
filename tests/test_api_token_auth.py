"""Signing in with an htMarquee API token instead of the admin password.

These run the REAL api client and the real config-flow steps against a real HTTP
server on localhost that answers the way the device does (same status codes, same
`detail` strings as `backend/middleware/auth.py` in the app). Nothing in the client
or the flow is mocked; the only stand-in is the device itself.

    python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("homeassistant", reason="needs `pip install homeassistant`")

from aiohttp import web  # noqa: E402

from custom_components.htmarquee.api import (  # noqa: E402
    HtMarqueeApi,
    HtMarqueeAuthError,
)
from custom_components.htmarquee.config_flow import (  # noqa: E402
    HtMarqueeConfigFlow,
    uses_api_token,
)
from custom_components.htmarquee.const import (  # noqa: E402
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USERNAME,
)

GOOD_TOKEN = "htm_goodgoodgoodgoodgoodgoodgoodgood"
REVOKED_TOKEN = "htm_revokedrevokedrevokedrevokedrev"

_COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "htmarquee"


class FakeDevice:
    """A localhost HTTP server that authenticates like htMarquee 1.6.0."""

    def __init__(self) -> None:
        self.login_attempts = 0
        self.port = 0
        self._runner: web.AppRunner | None = None

    async def _version(self, request: web.Request) -> web.Response:
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if bearer == GOOD_TOKEN:
            return web.json_response({"version": "1.6.0", "state": "idle"})
        if bearer.startswith("htm_"):
            # Verbatim from the device's auth middleware.
            return web.json_response(
                {"detail": "Invalid, expired, or revoked API token"}, status=403
            )
        return web.json_response({"detail": "Invalid or expired token"}, status=403)

    async def _login(self, request: web.Request) -> web.Response:
        self.login_attempts += 1
        return web.json_response({"detail": "Invalid credentials"}, status=401)

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/system/version", self._version)
        app.router.add_post("/api/auth/login", self._login)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


def run(coro_fn: Any) -> Any:
    """Run an async test body against a started FakeDevice."""

    async def _main() -> Any:
        device = FakeDevice()
        await device.start()
        try:
            return await coro_fn(device)
        finally:
            await device.stop()

    return asyncio.run(_main())


def make_flow(device: FakeDevice) -> HtMarqueeConfigFlow:
    flow = HtMarqueeConfigFlow()
    flow._host = "127.0.0.1"
    flow._port = device.port
    flow._use_ssl = False
    return flow


# ── API client ──────────────────────────────────────────────────────────


def test_a_working_token_validates():
    async def body(device: FakeDevice) -> None:
        api = HtMarqueeApi("127.0.0.1", device.port, use_ssl=False, token=GOOD_TOKEN)
        try:
            await api.async_validate_token()
        finally:
            await api.close()

    run(body)


def test_a_revoked_token_is_an_auth_error_and_never_triggers_a_login():
    """A token-only entry has no password. When the device rejects the token the
    client must raise the auth error (which starts Home Assistant's reauth flow),
    not try to log in with credentials it does not have."""

    async def body(device: FakeDevice) -> None:
        api = HtMarqueeApi("127.0.0.1", device.port, use_ssl=False, token=REVOKED_TOKEN)
        try:
            with pytest.raises(HtMarqueeAuthError):
                await api.async_get_system_version()  # the ordinary, retrying request path
            with pytest.raises(HtMarqueeAuthError):
                await api.async_validate_token()
        finally:
            await api.close()
        assert device.login_attempts == 0

    run(body)


# ── Config flow ─────────────────────────────────────────────────────────


def test_token_check_accepts_a_good_token_and_names_each_failure():
    async def body(device: FakeDevice) -> None:
        flow = make_flow(device)
        assert await flow._async_check_api_token(GOOD_TOKEN) is None
        assert await flow._async_check_api_token(REVOKED_TOKEN) == "invalid_token"
        # A pasted password is caught by its shape, before any request is made.
        assert await flow._async_check_api_token("hunter2") == "invalid_token_format"

    run(body)


def test_token_check_reports_an_unreachable_device_as_a_connection_problem():
    async def body(device: FakeDevice) -> None:
        flow = make_flow(device)
        await device.stop()  # the port is now closed: a real connection failure
        assert await flow._async_check_api_token(GOOD_TOKEN) == "cannot_connect"

    run(body)


def test_api_token_step_shows_the_form_again_with_the_error_on_a_bad_token():
    async def body(device: FakeDevice) -> None:
        flow = make_flow(device)
        first = await flow.async_step_api_token()
        assert first["type"] == "form" and first["step_id"] == "api_token"
        assert not first["errors"]

        result = await flow.async_step_api_token({CONF_TOKEN: f"  {REVOKED_TOKEN}  "})
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_token"}

    run(body)


@pytest.mark.parametrize(("auth_mode", "second"), [("password", "auth"), ("pin", "auth_pin")])
def test_auth_method_menu_offers_the_token_and_the_devices_own_mode(auth_mode, second):
    async def body(device: FakeDevice) -> None:
        flow = make_flow(device)
        flow._auth_mode = auth_mode
        menu = await flow.async_step_auth_method()
        assert menu["type"] == "menu"
        assert menu["menu_options"] == ["api_token", second]
        # Every menu option must be a real step, or Home Assistant fails at click time.
        for option in menu["menu_options"]:
            assert hasattr(flow, f"async_step_{option}")

    run(body)


def test_uses_api_token_tells_token_entries_from_password_entries():
    base = {CONF_HOST: "htmarquee.local", CONF_PORT: 443}
    assert uses_api_token({**base, CONF_TOKEN: GOOD_TOKEN}) is True
    # A password entry also stores a token (its last login session, a JWT).
    assert uses_api_token(
        {**base, CONF_TOKEN: "eyJhbGciOi.session.jwt", CONF_USERNAME: "admin", CONF_PASSWORD: "pw"}
    ) is False
    # No auth at all.
    assert uses_api_token(base) is False


# ── Strings ─────────────────────────────────────────────────────────────


def test_every_new_step_and_error_has_text_in_both_string_files():
    strings = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((_COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == english

    steps = strings["config"]["step"]
    for step in ("auth_method", "api_token", "reauth_api_token"):
        assert step in steps
    assert set(steps["auth_method"]["menu_options"]) == {"api_token", "auth", "auth_pin"}
    for error in ("invalid_token", "invalid_token_format"):
        assert error in strings["config"]["error"]
