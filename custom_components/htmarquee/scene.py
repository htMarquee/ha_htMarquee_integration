"""Scene platform for htMarquee — one scene per saved LED preset.

A preset is a named snapshot of the whole strip (effect, palette, colour,
brightness, power), which is exactly what a Home Assistant scene is. Exposing
them as scenes means a "Movie Night" automation can activate the device's own
saved look instead of reassembling it from effect + palette + colour calls.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant, callback
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
    """Create a scene per LED preset, and follow presets added later."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _sync_presets() -> None:
        """Add entities for presets that appeared since the last poll.

        Presets are created on the device, not in Home Assistant, so the set
        changes underneath us. Removals are deliberately *not* handled by
        deleting entities — an entity that vanishes takes its automations'
        references with it. A deleted preset's scene goes unavailable
        instead, which is visible and reversible.
        """
        new = [p for p in coordinator.led_presets if p.get("id") not in known]
        if not new:
            return
        known.update(p["id"] for p in new)
        async_add_entities(HtMarqueeLedPresetScene(coordinator, entry, p) for p in new)

    _sync_presets()
    entry.async_on_unload(coordinator.async_add_listener(_sync_presets))


class HtMarqueeLedPresetScene(HtMarqueeLedEntity, Scene):
    """Applies one saved LED preset to the strip."""

    _attr_icon = "mdi:lightbulb-group"

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
        preset: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry, f"led_preset_{preset['id']}")
        self._preset_id: int = preset["id"]
        self._last_name: str = preset.get("name", f"Preset {self._preset_id}")

    @property
    def _preset(self) -> dict[str, Any] | None:
        return next(
            (p for p in self.coordinator.led_presets if p.get("id") == self._preset_id), None
        )

    @property
    def name(self) -> str:
        # Renaming a preset on the device renames the scene here too. The
        # entity_id is fixed at creation, so only the friendly name moves.
        preset = self._preset
        if preset and preset.get("name"):
            self._last_name = preset["name"]
        return f"LED {self._last_name}"

    @property
    def available(self) -> bool:
        return super().available and self._preset is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        preset = self._preset or {}
        return {
            "effect": preset.get("effect"),
            "palette": preset.get("palette"),
            "power": preset.get("power"),
            # Set when the preset is bound to a playlist: activating that
            # playlist on the device applies this preset automatically.
            "playlist_id": preset.get("playlist_id"),
        }

    async def async_activate(self, **kwargs: Any) -> None:
        """Apply the preset to the strip."""
        try:
            await self.coordinator.api.async_apply_led_preset(self._preset_id)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED presets require htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"Could not apply LED preset: {err}") from err
        await self.coordinator.async_refresh_hardware()
