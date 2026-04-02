"""Light platform for htMarquee LED strip."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
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
    """Set up htMarquee LED light."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeLedLight(coordinator, entry)])


class HtMarqueeLedLight(CoordinatorEntity[HtMarqueeCoordinator], LightEntity):
    """LED strip controlled via htMarquee API."""

    _attr_has_entity_name = True
    _attr_name = "LED Strip"
    _attr_icon = "mdi:led-strip-variant"
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_led"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "htMarquee",
            "manufacturer": MANUFACTURER,
            "model": "Smart Movie Poster Display",
        }

    @property
    def _led_state(self) -> dict[str, Any]:
        return self.coordinator.hardware.get("led", {})

    @property
    def available(self) -> bool:
        if not self.coordinator.is_premiere:
            return False
        return (
            super().available
            and self.coordinator.hardware.get("led_enabled", False)
        )

    @property
    def is_on(self) -> bool | None:
        return self._led_state.get("on")

    @property
    def brightness(self) -> int | None:
        """Return 0-255 brightness."""
        return self._led_state.get("brightness")

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        color = self._led_state.get("color")
        if isinstance(color, list) and len(color) == 3:
            return tuple(color)
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on LED strip with optional brightness and color."""
        try:
            await self.coordinator.api.async_led_power(True)

            if ATTR_BRIGHTNESS in kwargs:
                await self.coordinator.api.async_led_brightness(kwargs[ATTR_BRIGHTNESS])

            if ATTR_RGB_COLOR in kwargs:
                r, g, b = kwargs[ATTR_RGB_COLOR]
                await self.coordinator.api.async_led_color(r, g, b)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off LED strip."""
        try:
            await self.coordinator.api.async_led_power(False)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()
