"""DataUpdateCoordinator for htMarquee."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HtMarqueeApi, HtMarqueeApiError, HtMarqueeAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, HARDWARE_SCAN_INTERVAL, PLAYLIST_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class HtMarqueeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls htMarquee /api/status."""

    def __init__(self, hass: HomeAssistant, api: HtMarqueeApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self._playlist_tick = 0
        self._hardware_tick = 0
        self.playlists: list[dict[str, Any]] = []
        self.hardware: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.async_get_status()
        except HtMarqueeAuthError as err:
            raise UpdateFailed(f"Auth error: {err}") from err
        except HtMarqueeApiError as err:
            raise UpdateFailed(f"API error: {err}") from err

        # Refresh playlists less frequently
        self._playlist_tick += DEFAULT_SCAN_INTERVAL
        if self._playlist_tick >= PLAYLIST_SCAN_INTERVAL:
            self._playlist_tick = 0
            try:
                self.playlists = await self.api.async_get_playlists()
            except HtMarqueeApiError:
                _LOGGER.debug("Failed to refresh playlists")

        # Refresh hardware status less frequently
        self._hardware_tick += DEFAULT_SCAN_INTERVAL
        if self._hardware_tick >= HARDWARE_SCAN_INTERVAL:
            self._hardware_tick = 0
            try:
                self.hardware = await self.api.async_get_hardware_status()
            except HtMarqueeApiError:
                _LOGGER.debug("Failed to refresh hardware status")

        return status
