"""DataUpdateCoordinator for htMarquee."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HtMarqueeApi, HtMarqueeApiError, HtMarqueeAuthError
from .const import (
    CATALOG_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HARDWARE_SCAN_INTERVAL,
    PLAYLIST_SCAN_INTERVAL,
    TIER_MATINEE,
    TIER_PREMIERE,
)

_LOGGER = logging.getLogger(__name__)


class HtMarqueeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls /api/status every tick, plus slower groups on their own deadlines.

    The device exposes far more than the slideshow status, but most of it
    changes rarely (palettes, presets) or is expensive to produce
    (/api/hardware/status shells out to xrandr). Each group therefore carries
    a monotonic deadline instead of riding the 10s tick. All deadlines start
    at 0 so the *first* refresh primes everything — an earlier tick-counter
    version only reached its thresholds after 30-60 seconds, which left the
    LED light, the TV buttons and the playlist source list unavailable for
    the first minute after every Home Assistant restart.
    """

    def __init__(self, hass: HomeAssistant, api: HtMarqueeApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.playlists: list[dict[str, Any]] = []
        self.hardware: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {}
        self.version: dict[str, Any] = {}
        self.led_presets: list[dict[str, Any]] = []
        self.led_palettes: list[dict[str, Any]] = []
        self.showtimes: list[dict[str, Any]] = []
        # None = not yet probed. Set False when the device refuses the
        # endpoint (403 on Matinee, 404 on firmware predating the feature)
        # so the platform can skip creating a permanently-unknown entity.
        self.showtimes_supported: bool | None = None
        self.tier: str = TIER_MATINEE  # fail closed; upgraded once confirmed
        self.device_sw_version: str | None = None
        self._next_hardware = 0.0
        self._next_playlists = 0.0
        self._next_catalog = 0.0

    @property
    def is_premiere(self) -> bool:
        """Return True if the device has a Premiere subscription."""
        return self.tier == TIER_PREMIERE

    @property
    def led(self) -> dict[str, Any]:
        """LED sub-state, or {} when the strip is disabled.

        /api/hardware/status sends ``"led": null`` when the LED service is
        not running, so a plain ``.get("led", {})`` hands back None and every
        caller then trips over ``None.get``.
        """
        return self.hardware.get("led") or {}

    @property
    def cec(self) -> dict[str, Any]:
        """CEC sub-state, or {} when no adapter is present."""
        return self.hardware.get("cec") or {}

    @property
    def led_speed(self) -> int:
        """Current effect speed, falling back to the middle of the slider.

        Checked against None rather than truthiness: 0 is a legal speed (the
        slowest end of the range), and `or 128` would silently snap a
        deliberately slow strip back to default on the next colour change.
        """
        speed = self.led.get("speed")
        return 128 if speed is None else int(speed)

    @property
    def led_effect_name(self) -> str:
        """Running effect, or 'solid' when the strip isn't running one."""
        name = self.led.get("effect_name")
        return name if name else "solid"

    @property
    def led_enabled(self) -> bool:
        return bool(self.hardware.get("led_enabled"))

    @property
    def cec_enabled(self) -> bool:
        return bool(self.hardware.get("cec_enabled"))

    async def _async_update_data(self) -> dict[str, Any]:
        # ONE auth handler around the whole refresh, not just the status call.
        # /api/status is a PUBLIC endpoint on the device (the display itself reads
        # it), so it keeps answering 200 after the credential stops working. The
        # only place a revoked API token or a changed password shows up is in the
        # slower groups below - and those used to swallow every error. The result,
        # seen live on 2026-11-24 after a token was revoked: the entry stayed
        # "loaded", every entity stayed available with frozen values, and Home
        # Assistant never asked for a new token.
        # ConfigEntryAuthFailed is what makes Home Assistant start the reauth flow;
        # UpdateFailed would just retry forever with the dead credential.
        try:
            try:
                status = await self.api.async_get_status()
            except HtMarqueeAuthError:
                raise
            except HtMarqueeApiError as err:
                raise UpdateFailed(f"API error: {err}") from err

            # Track license tier from status response
            new_tier = status.get("license_tier", self.tier)
            if new_tier != self.tier:
                _LOGGER.info("htMarquee tier changed: %s -> %s", self.tier, new_tier)
                self.tier = new_tier

            now = time.monotonic()
            if now >= self._next_hardware:
                self._next_hardware = now + HARDWARE_SCAN_INTERVAL
                await self._async_refresh_hardware_group()
            if now >= self._next_playlists:
                self._next_playlists = now + PLAYLIST_SCAN_INTERVAL
                await self._fetch("playlists", self.api.async_get_playlists)
                await self._fetch("led_presets", self.api.async_get_led_presets)
            if now >= self._next_catalog:
                self._next_catalog = now + CATALOG_SCAN_INTERVAL
                await self._fetch("led_palettes", self.api.async_get_led_palettes)
                await self._async_refresh_showtimes()
        except HtMarqueeAuthError as err:
            # The group that failed must be tried again on the very next tick, or a
            # reauth that Home Assistant has not started yet would wait out the
            # group's deadline first.
            self._next_hardware = self._next_playlists = self._next_catalog = 0.0
            raise ConfigEntryAuthFailed(f"Auth error: {err}") from err

        return status

    async def _fetch(self, attr: str, call: Any) -> None:
        """Refresh one optional attribute, keeping the last good value.

        Every group here is optional: an older device may 404 the endpoint
        and a Matinee device 403s the Premiere ones. None of that should
        take down the media player, so failures only log at debug level.
        """
        try:
            setattr(self, attr, await call())
        except HtMarqueeAuthError:
            # Not optional: a rejected credential is the caller's to report (see
            # _async_update_data). It is a subclass of HtMarqueeApiError, so
            # without this clause the line below would swallow it.
            raise
        except HtMarqueeApiError as err:
            _LOGGER.debug("Failed to refresh %s: %s", attr, err)

    async def _async_refresh_hardware_group(self) -> None:
        """LED/CEC state, system metrics and version — the 30s group."""
        await self._fetch("hardware", self.api.async_get_hardware_status)
        await self._fetch("metrics", self.api.async_get_hardware_metrics)
        try:
            self.version = await self.api.async_get_system_version()
            self.device_sw_version = self.version.get("version")
        except HtMarqueeAuthError:
            raise
        except HtMarqueeApiError as err:
            _LOGGER.debug("Failed to refresh device version: %s", err)

    async def _async_refresh_showtimes(self) -> None:
        """Scheduled showings — Premiere-gated, so absence is expected."""
        try:
            self.showtimes = await self.api.async_get_showtimes()
            self.showtimes_supported = True
        except HtMarqueeAuthError:
            raise
        except HtMarqueeApiError as err:
            if self.showtimes_supported is None:
                self.showtimes_supported = False
            _LOGGER.debug("Scheduled showtimes unavailable: %s", err)

    async def async_refresh_hardware(self) -> None:
        """Re-read hardware state now and push it to entities.

        Anything that writes to the LED strip or the TV calls this instead of
        ``async_request_refresh()``: that only re-polls /api/status, so a
        colour or effect change sat stale in Home Assistant until the 30s
        hardware deadline came round.
        """
        self._next_hardware = time.monotonic() + HARDWARE_SCAN_INTERVAL
        try:
            await self._async_refresh_hardware_group()
        except HtMarqueeAuthError:
            # Called right after a command, outside the polling loop, so there is no
            # ConfigEntryAuthFailed to raise here. Make the next poll re-read this
            # group at once; that poll reports the rejected credential properly.
            self._next_hardware = 0.0
            await self.async_request_refresh()
            return
        self.async_update_listeners()

    async def async_refresh_led_presets(self) -> None:
        """Re-read saved LED presets now (after one is applied elsewhere)."""
        await self._fetch("led_presets", self.api.async_get_led_presets)
        self.async_update_listeners()
