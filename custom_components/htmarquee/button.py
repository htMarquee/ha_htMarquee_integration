"""Button platform for htMarquee."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueePremiumRequired
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity


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


class HtMarqueePlayTrailerButton(HtMarqueeEntity, ButtonEntity):
    """Button to play the current movie's trailer."""

    _attr_name = "Play Trailer"
    _attr_icon = "mdi:movie-play"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "play_trailer")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_premiere

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_play_trailer()
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("Play Trailer requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()


class _HtMarqueeCecButton(HtMarqueeEntity, ButtonEntity):
    """Fire-and-forget CEC power command.

    Superseded by switch.htmarquee_tv, which does the same thing *and*
    reports the TV's state. These stay so existing automations keep working,
    and because a dashboard toggle already showing "on" cannot be tapped to
    re-assert "on" at a TV that ignored the first command.
    """

    _command: str

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_premiere and self.coordinator.cec_enabled

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_cec_power(self._command)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("CEC control requires htMarquee Premiere tier") from err
        await self.coordinator.async_request_refresh()


class HtMarqueeTvOnButton(_HtMarqueeCecButton):
    """Button to turn TV on via CEC."""

    _attr_name = "TV On"
    _attr_icon = "mdi:television"
    _command = "on"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "tv_on")


class HtMarqueeTvOffButton(_HtMarqueeCecButton):
    """Button to turn TV off via CEC."""

    _attr_name = "TV Off"
    _attr_icon = "mdi:television-off"
    _command = "off"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "tv_off")
