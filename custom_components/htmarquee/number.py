"""Number platform for htMarquee — LED effect speed."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError, HtMarqueePremiumRequired
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee numbers."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeLedSpeedNumber(coordinator, entry)])


class HtMarqueeLedSpeedNumber(HtMarqueeLedEntity, NumberEntity):
    """Effect speed, matching the device's 0-255 slider.

    The scale is not linear: the device maps the slider through an
    exponential curve where the midpoint is each effect's natural tempo, the
    top is roughly 7.5x that and the bottom roughly an eighth. Halving the
    number does not halve the speed.
    """

    _attr_name = "LED Effect Speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "led_speed")

    @property
    def native_value(self) -> float | None:
        speed = self.coordinator.led.get("speed")
        return float(speed) if speed is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Re-issue the running effect at the new speed.

        Speed is an argument of /api/led/effect rather than an endpoint of
        its own, so the current effect and palette ride along unchanged. The
        device restarts the effect to apply it — expect a visible cut.
        """
        try:
            await self.coordinator.api.async_led_effect(
                self.coordinator.led_effect_name,
                int(value),
                self.coordinator.led.get("palette_name"),
            )
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee rejected the speed change: {err}") from err
        await self.coordinator.async_refresh_hardware()
