"""API client for htMarquee."""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from collections.abc import Callable
from typing import Any

import aiohttp

from homeassistant.util.ssl import get_default_no_verify_context

_LOGGER = logging.getLogger(__name__)

# The device reports a dead JWT as HTTP 403 with a *string* detail
# ({"detail": "Invalid or expired token"}), not the 401 this client was
# originally written against. Recognising it is what lets _request
# re-login instead of raising a generic ApiError and leaving the token
# stale forever. Kept deliberately loose: the wording is the device's to
# change, and a missed match silently breaks every image again.
_TOKEN_REJECTED_RE = re.compile(
    r"(invalid|expired|missing)[^.]*\btoken\b"
    r"|\btoken\b[^.]*(invalid|expired)"
    r"|not authenticated",
    re.IGNORECASE,
)


class HtMarqueeApiError(Exception):
    """API communication error."""


class HtMarqueeAuthError(HtMarqueeApiError):
    """Authentication error."""


class HtMarqueePremiumRequired(HtMarqueeApiError):
    """Raised when a Premiere-tier feature is called on a Matinee subscription."""


class HtMarqueeApi:
    """Async API client for htMarquee."""

    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool = True,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        session: aiohttp.ClientSession | None = None,
        token_updated_cb: Callable[[str], None] | None = None,
    ) -> None:
        # Called with each freshly minted token so the caller can persist
        # it; without it a refresh lives only until the next restart.
        self._token_updated_cb = token_updated_cb
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._token = token
        self._username = username
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._relogin_lock = asyncio.Lock()
        scheme = "https" if use_ssl else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        # The device presents a self-signed cert from its own CA, with a CN
        # that doesn't match the configured host, so verification has to be
        # off either way. Home Assistant's shared no-verify context is
        # exactly that pairing (check_hostname=False, verify_mode=CERT_NONE)
        # and every variant of it is built once at import time.
        #
        # Building one here with ssl.create_default_context() instead read
        # the system CA bundle off disk on every setup — blocking I/O inside
        # the event loop, which HA warned about on every start — and then
        # CERT_NONE threw that bundle away unused.
        #
        # Never mutate this context: it is shared with every other caller in
        # the process. It already has the settings this client needs.
        self._ssl_context: ssl.SSLContext | None = (
            get_default_no_verify_context() if use_ssl else None
        )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            self._session = aiohttp.ClientSession(connector=connector)
            self._owns_session = True
        return self._session

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @property
    def base_url(self) -> str:
        """Root URL of the device — used for the HA device's 'Visit' link."""
        return self._base_url

    async def _do_request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Execute a single HTTP request with no retry logic."""
        session = await self._ensure_session()
        url = f"{self._base_url}{path}"
        try:
            async with session.request(
                method, url, headers=self._headers(), json=json, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    raise HtMarqueeAuthError("Authentication failed")
                if resp.status == 403:
                    try:
                        body = await resp.json()
                    except Exception:
                        raise HtMarqueeApiError("Forbidden (status 403)")
                    # The device's @require_tier gate returns detail as a dict:
                    # {"error": "premiere_required", "message": ..., "feature": ..., "current_tier": ...}
                    detail = body.get("detail")
                    if isinstance(detail, dict) and detail.get("error") == "premiere_required":
                        raise HtMarqueePremiumRequired(
                            detail.get("message", "This feature requires a Premiere license.")
                        )
                    # A rejected token arrives here too -- same 403, but a
                    # string detail rather than the tier gate's dict. Raise
                    # AuthError so _request refreshes and retries.
                    if isinstance(detail, str) and _TOKEN_REJECTED_RE.search(detail):
                        raise HtMarqueeAuthError(f"Token rejected: {detail}")
                    raise HtMarqueeApiError(f"Forbidden: {body}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise HtMarqueeApiError(f"API error {resp.status}: {text[:200]}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise HtMarqueeApiError(f"Connection error: {err}") from err

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Execute a request with automatic token refresh on 401.

        Returns whatever the endpoint sends — most return an object, but the
        list endpoints (playlists, presets, showtimes) return a JSON array.
        """
        try:
            return await self._do_request(method, path, json, params)
        except HtMarqueeAuthError:
            if not self._username or not self._password:
                raise
            # Re-login under lock; concurrent callers wait then retry
            stale_token = self._token
            async with self._relogin_lock:
                if self._token == stale_token:
                    try:
                        await self.async_login(self._username, self._password)
                        _LOGGER.info("htMarquee token refreshed after 401")
                    except (HtMarqueeAuthError, HtMarqueeApiError) as login_err:
                        raise HtMarqueeAuthError(
                            f"Authentication failed and re-login unsuccessful: {login_err}"
                        ) from login_err
            # Retry once with fresh token — no further retry on failure
            return await self._do_request(method, path, json, params)

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # ── Auth ────────────────────────────────────────────────────────────

    async def async_login(self, username: str, password: str) -> str:
        """Login and return JWT token."""
        session = await self._ensure_session()
        url = f"{self._base_url}/api/auth/login"
        async with session.post(
            url,
            headers={"Accept": "application/json"},
            json={"username": username, "password": password},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                raise HtMarqueeAuthError("Invalid credentials")
            if resp.status >= 400:
                raise HtMarqueeApiError(f"Login failed: {resp.status}")
            data = await resp.json()
            # Token comes back in Set-Cookie header; also extract from response
            token = data.get("token")
            if not token:
                # Extract from cookie
                cookie = resp.cookies.get("htmarquee_token")
                if cookie:
                    token = cookie.value
            if not token:
                raise HtMarqueeApiError("No token in login response")
            self._token = token
            if self._token_updated_cb is not None:
                self._token_updated_cb(token)
            return token

    async def async_get_auth_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/auth/status")

    # ── Status ──────────────────────────────────────────────────────────

    async def async_get_health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/health")

    async def async_get_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/status")

    async def async_get_license_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/license/status")

    async def async_get_system_version(self) -> dict[str, Any]:
        """Fetch device version/update state (GET /api/system/version)."""
        return await self._request("GET", "/api/system/version")

    # ── OTA updates ─────────────────────────────────────────────────────

    async def async_check_update(self) -> dict[str, Any]:
        """Ask the device to re-read its update manifest.

        This is not optional bookkeeping: the install endpoint applies
        whatever descriptor the last *check* cached, so installing without
        checking first either no-ops or installs a stale target.
        """
        return await self._request("POST", "/api/system/update/check")

    async def async_install_update(self) -> dict[str, Any]:
        """Start installing the available update (device restarts itself)."""
        return await self._request("POST", "/api/system/update/install")

    # ── Control ─────────────────────────────────────────────────────────

    async def async_skip(self) -> dict[str, Any]:
        return await self._request("POST", "/api/control/skip")

    async def async_previous(self) -> dict[str, Any]:
        return await self._request("POST", "/api/control/previous")

    async def async_pause(self) -> dict[str, Any]:
        return await self._request("POST", "/api/control/pause")

    async def async_resume(self) -> dict[str, Any]:
        return await self._request("POST", "/api/control/resume")

    async def async_play_trailer(self) -> dict[str, Any]:
        return await self._request("POST", "/api/control/play-trailer")

    async def async_manual(self, tmdb_id: int) -> dict[str, Any]:
        return await self._request("POST", "/api/control/manual", json={"tmdb_id": tmdb_id})

    # ── Search ──────────────────────────────────────────────────────────

    async def async_search_movies(self, query: str) -> dict[str, Any]:
        """Search for movies by title. Returns {results: [...], ...}."""
        return await self._request("GET", "/api/movie/search", params={"q": query})

    # ── Playlists ───────────────────────────────────────────────────────

    async def async_get_playlists(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/playlists")

    async def async_activate_playlist(self, playlist_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/playlists/{playlist_id}/activate")

    async def async_deactivate_playlist(self) -> dict[str, Any]:
        return await self._request("POST", "/api/playlists/deactivate")

    # ── Hardware ────────────────────────────────────────────────────────

    async def async_get_hardware_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/hardware/status")

    async def async_get_hardware_metrics(self) -> dict[str, Any]:
        """CPU/RAM/temperature/uptime snapshot (GET /api/hardware/metrics)."""
        return await self._request("GET", "/api/hardware/metrics")

    async def async_cec_power(self, command: str) -> dict[str, Any]:
        return await self._request("POST", "/api/cec/power", json={"command": command})

    # ── LED strip ───────────────────────────────────────────────────────

    async def async_led_power(self, state: bool) -> dict[str, Any]:
        return await self._request("POST", "/api/led/power", json={"state": state})

    async def async_led_brightness(self, brightness: int) -> dict[str, Any]:
        return await self._request("POST", "/api/led/brightness", json={"brightness": brightness})

    async def async_led_color(self, r: int, g: int, b: int) -> dict[str, Any]:
        return await self._request("POST", "/api/led/color", json={"r": r, "g": g, "b": b})

    async def async_led_effect(
        self, effect: str, speed: int, palette: str | None = None
    ) -> dict[str, Any]:
        """Start a named effect. Also powers the strip on, device-side.

        Effect, speed and palette travel together because the device
        restarts the running effect on every change — sending them as one
        call is both fewer round trips and one visible restart instead of
        three.
        """
        body: dict[str, Any] = {"effect": effect, "speed": speed}
        if palette:
            body["palette"] = palette
        return await self._request("POST", "/api/led/effect", json=body)

    async def async_led_follow_state(self, enabled: bool) -> dict[str, Any]:
        """Toggle 'follow display state' (LED auto-mode) on the device."""
        return await self._request("POST", "/api/led/follow-state", json={"enabled": enabled})

    async def async_get_led_palettes(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/led/palettes")
        palettes: list[dict[str, Any]] = data.get("palettes", [])
        return palettes

    async def async_get_led_presets(self) -> list[dict[str, Any]]:
        presets: list[dict[str, Any]] = await self._request("GET", "/api/led/presets")
        return presets

    async def async_apply_led_preset(self, preset_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/led/presets/{preset_id}/apply")

    # ── Scheduled showtimes ─────────────────────────────────────────────

    async def async_get_showtimes(self) -> list[dict[str, Any]]:
        """Scheduled showings. Premiere-only — 403 on a Matinee device."""
        showtimes: list[dict[str, Any]] = await self._request("GET", "/api/scheduled-showtimes")
        return showtimes

    # ── Convenience ─────────────────────────────────────────────────────

    def get_poster_url(self, poster_path: str) -> str:
        """Build full poster URL from a relative asset path."""
        if not poster_path:
            return ""
        if poster_path.startswith("http"):
            return poster_path
        return f"{self._base_url}{poster_path}"

    async def _do_get_image(self, url: str) -> tuple[bytes, str] | None:
        """One image fetch attempt.

        Raises HtMarqueeAuthError when the token was rejected so the caller
        can refresh; returns None for any other failure.
        """
        session = await self._ensure_session()
        async with session.get(
            url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status in (401, 403):
                detail = ""
                try:
                    body = await resp.json()
                    raw = body.get("detail")
                    detail = raw if isinstance(raw, str) else ""
                except Exception:  # noqa: BLE001 - body may not be JSON
                    pass
                if resp.status == 401 or _TOKEN_REJECTED_RE.search(detail):
                    raise HtMarqueeAuthError(
                        f"Image request rejected ({resp.status}): {detail or 'no detail'}"
                    )
            if resp.status != 200:
                _LOGGER.warning(
                    "htMarquee image fetch failed: %s returned HTTP %s", url, resp.status
                )
                return None
            content_type = resp.content_type or "image/jpeg"
            return await resp.read(), content_type

    async def async_get_image(self, path: str) -> tuple[bytes, str] | None:
        """Fetch an image, re-logging in once if the token has expired.

        Assets are the only place this client reads raw bytes instead of
        JSON, so it cannot go through _request; this repeats _request's
        refresh-on-auth-failure logic instead. It previously swallowed every
        non-200 as None, which meant an expired token turned all three image
        entities into broken images with nothing in the log -- /api/status
        kept returning 200, so the integration otherwise looked healthy.
        """
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        try:
            return await self._do_get_image(url)
        except HtMarqueeAuthError as err:
            if not self._username or not self._password:
                _LOGGER.warning(
                    "htMarquee image auth failed and no stored credentials to "
                    "re-login with: %s", err
                )
                return None
            # Same guarded re-login as _request: concurrent image fetches
            # wait on the lock, then find the token already refreshed.
            stale_token = self._token
            async with self._relogin_lock:
                if self._token == stale_token:
                    try:
                        await self.async_login(self._username, self._password)
                        _LOGGER.info(
                            "htMarquee token refreshed after an image request was rejected"
                        )
                    except (HtMarqueeAuthError, HtMarqueeApiError) as login_err:
                        _LOGGER.warning(
                            "htMarquee re-login failed during image fetch: %s", login_err
                        )
                        return None
            try:
                return await self._do_get_image(url)
            except HtMarqueeAuthError as retry_err:
                _LOGGER.warning(
                    "htMarquee image still rejected after refresh: %s", retry_err
                )
                return None
        except aiohttp.ClientError as err:
            _LOGGER.warning("htMarquee image fetch error for %s: %s", url, err)
            return None
