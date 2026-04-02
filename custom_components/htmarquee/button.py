"""Button platform for htMarquee."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HtMarqueeConfigEntry
from .api import HtMarqueePremiumRequired
from .const import DOMAIN, MANUFACTURER
from .coordinator import HtMarqueeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee buttons."""
    coordinator = entry.runtime_data
    async_add_entities([
        HtMarqueePlayTrailerButton(coordinator, entry),
        HtMarqueeTvOnButton(coordinator, entry),
        HtMarqueeTvOffButton(coordinator, entry),
    ])


class _HtMarqueeButton(CoordinatorEntity[HtMarqueeCoordinator], ButtonEntity):
    """Base button with shared device info."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "htMarquee",
            "manufacturer": MANUFACTURER,
            "model": "Smart Movie Poster Display",
        }


class HtMarqueePlayTrailerButton(_HtMarqueeButton):
    """Button to play the current movie's trailer."""

    _attr_name = "Play Trailer"
    _attr_icon = "mdi:movie-play"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_play_trailer"

    @property
    def available(self) -> bool:
        if not self.coordinator.is_premiere:
            return False
        return super().available

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_play_trailer()
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("Play Trailer requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()


class HtMarqueeTvOnButton(_HtMarqueeButton):
    """Button to turn TV on via CEC."""

    _attr_name = "TV On"
    _attr_icon = "mdi:television"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tv_on"

    @property
    def available(self) -> bool:
        if not self.coordinator.is_premiere:
            return False
        return super().available and self.coordinator.hardware.get("cec_enabled", False)

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_cec_power("on")
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("CEC control requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()


class HtMarqueeTvOffButton(_HtMarqueeButton):
    """Button to turn TV off via CEC."""

    _attr_name = "TV Off"
    _attr_icon = "mdi:television-off"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tv_off"

    @property
    def available(self) -> bool:
        if not self.coordinator.is_premiere:
            return False
        return super().available and self.coordinator.hardware.get("cec_enabled", False)

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_cec_power("off")
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("CEC control requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()
