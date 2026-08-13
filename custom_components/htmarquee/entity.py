"""Shared entity base for htMarquee.

Every platform used to build its own ``device_info`` dict, and they had
drifted: only the media player carried ``sw_version``, so the device page
showed a firmware version or not depending on which entity Home Assistant
happened to register last. One base class keeps the device identity in a
single place and adds the "Visit device" link to the web UI.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HtMarqueeConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HtMarqueeCoordinator


class HtMarqueeEntity(CoordinatorEntity[HtMarqueeCoordinator]):
    """Coordinator-backed entity attached to the htMarquee device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        # `key` is part of the stored unique_id — changing one orphans the
        # user's entity and its history, so keep existing keys stable.
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="htMarquee",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=self.coordinator.device_sw_version,
            configuration_url=self.coordinator.api.base_url,
        )


class HtMarqueeLedEntity(HtMarqueeEntity):
    """Entity that drives the LED strip.

    The REST API is a Premiere feature and the strip also has to be enabled
    in the device's hardware settings, so both gates apply before any of
    these entities can do anything useful.
    """

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_premiere and self.coordinator.led_enabled
