"""Select platform for htMarquee — LED palette."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError, HtMarqueePremiumRequired
from .const import PALETTE_COLOR_PICKER_LABEL, palette_from_label, palette_label
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee selects."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeLedPaletteSelect(coordinator, entry)])


class HtMarqueeLedPaletteSelect(HtMarqueeLedEntity, SelectEntity):
    """Active LED palette, including any custom palettes on the device.

    Home Assistant lights have no concept of a palette, so it gets its own
    entity rather than being folded into the light's effect list — which
    would otherwise need one entry per effect/palette pair.
    """

    _attr_name = "LED Palette"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "led_palette")

    @property
    def _palette_names(self) -> list[str]:
        return [p["name"] for p in self.coordinator.led_palettes if p.get("name")]

    @property
    def options(self) -> list[str]:
        # "Color Picker" is a pseudo-palette meaning "ignore the palette and
        # use the picked colour". The device honours it but never lists it,
        # so prepend it exactly as the device's own web UI does.
        return [PALETTE_COLOR_PICKER_LABEL] + [palette_label(n) for n in self._palette_names]

    @property
    def current_option(self) -> str | None:
        active = self.coordinator.led.get("palette_name")
        if not active:
            return None
        label = palette_label(active)
        # A palette deleted on the device can linger in the reported state
        # for a poll or two; reporting an option that isn't in the list makes
        # Home Assistant log a warning, so report "unknown" instead.
        return label if label in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Re-issue the running effect with the chosen palette.

        The device has no standalone palette endpoint — palette is an
        argument of /api/led/effect — so the current effect and speed are
        sent back unchanged alongside it.
        """
        try:
            await self.coordinator.api.async_led_effect(
                self.coordinator.led_effect_name,
                self.coordinator.led_speed,
                palette_from_label(option, self._palette_names),
            )
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee rejected the palette change: {err}") from err
        await self.coordinator.async_refresh_hardware()
