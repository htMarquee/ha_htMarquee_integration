"""Update platform for htMarquee — surfaces the device's OTA updates."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError
from .const import MANUFACTURER
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity

# States the device's updater reports while an install is under way.
_BUSY_STATES = {"downloading", "verifying", "installing", "restarting"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the htMarquee update entity."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeUpdate(coordinator, entry)])


class HtMarqueeUpdate(HtMarqueeEntity, UpdateEntity):
    """Available htMarquee software update.

    The device never installs on its own — it only *detects* updates and
    waits for a human. This entity is that human's second front door, next
    to Settings -> Maintenance in the device's own web UI.
    """

    _attr_name = None  # the device name is the entity name for update entities
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    _attr_title = MANUFACTURER

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "update")

    @property
    def _available_update(self) -> dict[str, Any]:
        return self.coordinator.version.get("update_available") or {}

    @property
    def available(self) -> bool:
        # Older firmware has no /api/system/version; without it there is
        # nothing honest to report.
        return super().available and bool(self.coordinator.version)

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.version.get("version")

    @property
    def latest_version(self) -> str | None:
        # Home Assistant reads "up to date" as latest == installed, so with
        # no pending update the two must match rather than latest being None.
        return self._available_update.get("version") or self.installed_version

    @property
    def in_progress(self) -> bool:
        return self.coordinator.version.get("state") in _BUSY_STATES

    @property
    def auto_update(self) -> bool:
        # Deliberate device behaviour, not a missing feature: htMarquee
        # detects updates and waits to be told to install.
        return False

    @property
    def release_summary(self) -> str | None:
        # Home Assistant truncates this at 255 characters; the full text is
        # available through async_release_notes().
        changelog = self._available_update.get("changelog")
        return changelog[:255] if changelog else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        version = self.coordinator.version
        update = self._available_update
        return {
            "slot": version.get("slot"),
            "updater_state": version.get("state"),
            "can_rollback": version.get("can_rollback"),
            "last_check": version.get("last_check"),
            "last_error": version.get("last_error"),
            "released_at": update.get("released_at") or None,
            "size_bytes": update.get("size_bytes") or None,
        }

    async def async_release_notes(self) -> str | None:
        return self._available_update.get("changelog") or None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Install the available update.

        The check is mandatory, not defensive: the install endpoint applies
        whatever descriptor the last check cached, so installing without one
        either no-ops or installs a stale target.
        """
        try:
            await self.coordinator.api.async_check_update()
            result = await self.coordinator.api.async_install_update()
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee could not start the update: {err}") from err

        if result.get("status") == "error":
            raise HomeAssistantError(
                f"htMarquee refused the update: {result.get('message', 'unknown error')}"
            )

        # The device restarts itself partway through, so polling will fail
        # for a while — that is expected, and the coordinator recovers.
        await self.coordinator.async_refresh_hardware()
