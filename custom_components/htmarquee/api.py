"""API client for htMarquee."""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


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
    ) -> None:
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
        # Self-signed cert support — explicit context is more reliable than ssl=False
        if use_ssl:
            self._ssl_context: ssl.SSLContext | None = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        else:
            self._ssl_context = None

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

    async def _do_request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
                    if body.get("detail") == "Premiere feature required":
                        raise HtMarqueePremiumRequired(body["detail"])
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
    ) -> dict[str, Any]:
        """Execute a request with automatic token refresh on 401."""
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

    async def async_get_system_update_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/system/update/status")

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

    async def async_cec_power(self, command: str) -> dict[str, Any]:
        return await self._request("POST", "/api/cec/power", json={"command": command})

    async def async_led_power(self, state: bool) -> dict[str, Any]:
        return await self._request("POST", "/api/led/power", json={"state": state})

    async def async_led_brightness(self, brightness: int) -> dict[str, Any]:
        return await self._request("POST", "/api/led/brightness", json={"brightness": brightness})

    async def async_led_color(self, r: int, g: int, b: int) -> dict[str, Any]:
        return await self._request("POST", "/api/led/color", json={"r": r, "g": g, "b": b})

    # ── Convenience ─────────────────────────────────────────────────────

    def get_poster_url(self, poster_path: str) -> str:
        """Build full poster URL from a relative asset path."""
        if not poster_path:
            return ""
        if poster_path.startswith("http"):
            return poster_path
        return f"{self._base_url}{poster_path}"

    async def async_get_image(self, path: str) -> tuple[bytes, str] | None:
        """Fetch an image from htMarquee. Returns (content, content_type) or None."""
        session = await self._ensure_session()
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        try:
            async with session.get(
                url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                content_type = resp.content_type or "image/jpeg"
                return await resp.read(), content_type
        except aiohttp.ClientError:
            return None
