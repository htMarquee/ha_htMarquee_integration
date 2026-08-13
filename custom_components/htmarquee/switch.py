"""Switch platform for htMarquee — TV power (HDMI-CEC) and LED auto-mode."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError, HtMarqueePremiumRequired
from .const import CEC_SETTLE_SECONDS
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity, HtMarqueeLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            HtMarqueeTvSwitch(coordinator, entry),
            HtMarqueeFollowStateSwitch(coordinator, entry),
        ]
    )


class HtMarqueeTvSwitch(HtMarqueeEntity, SwitchEntity):
    """The TV in front of the marquee, over HDMI-CEC.

    This is the control to reach for — it is the only one that also *reports*
    whether the TV is on. The older TV On / TV Off buttons are kept so
    existing automations keep working, and because a dashboard toggle already
    showing "on" cannot be tapped to re-assert "on" at a TV that ignored the
    first CEC command.
    """

    _attr_name = "TV"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:television"

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "tv_power")
        self._cancel_settle: CALLBACK_TYPE | None = None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_premiere and self.coordinator.cec_enabled

    @property
    def is_on(self) -> bool | None:
        """None while the TV's power state is genuinely unknown.

        A flaky CEC adapter reports None rather than False, and guessing
        "off" there would make automations switch things off on a whim.
        """
        power = self.coordinator.cec.get("tv_power")
        return power if isinstance(power, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cec = self.coordinator.cec
        return {
            "tv_power_label": cec.get("tv_power_label"),
            "is_active_source": cec.get("is_active_source"),
            "osd_name": cec.get("osd_name"),
            "hdmi_port": cec.get("hdmi_port"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send("off")

    async def _async_send(self, command: str) -> None:
        try:
            await self.coordinator.api.async_cec_power(command)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("CEC control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee could not reach the TV: {err}") from err
        # /api/cec/power returns before the TV has responded — the device
        # runs the command in the background and puts its CEC monitor into
        # fast polling. Re-read once that settles instead of leaving the
        # switch showing the old state until the next 30s tick.
        self._schedule_settle_refresh()

    def _schedule_settle_refresh(self) -> None:
        if self._cancel_settle is not None:
            self._cancel_settle()
        self._cancel_settle = async_call_later(
            self.hass, CEC_SETTLE_SECONDS, self._async_settle_refresh
        )

    async def _async_settle_refresh(self, _now: datetime) -> None:
        self._cancel_settle = None
        await self.coordinator.async_refresh_hardware()

    async def async_will_remove_from_hass(self) -> None:
        # A pending timer would otherwise fire against a closed API session.
        if self._cancel_settle is not None:
            self._cancel_settle()
            self._cancel_settle = None
        await super().async_will_remove_from_hass()


class HtMarqueeFollowStateSwitch(HtMarqueeLedEntity, SwitchEntity):
    """'Follow display state' — let the slideshow drive the LEDs.

    On, the strip tracks what the display is doing (warm ambient while idle,
    dimmed during playback). Off, it holds whatever look you set. The device
    turns this off by itself the moment anyone takes manual control of the
    strip, including this integration, so expect it to flip after a colour or
    effect change.
    """

    _attr_name = "LED Follow Display State"
    _attr_icon = "mdi:television-ambient-light"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "led_follow_state")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.led.get("follow_display_state")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self.coordinator.api.async_led_follow_state(enabled)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee rejected the change: {err}") from err
        await self.coordinator.async_refresh_hardware()
