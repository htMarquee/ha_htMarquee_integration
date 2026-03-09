"""Switch platform for htMarquee."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee switches (none currently)."""
    # TV power moved to discrete buttons; this platform kept for future use
