"""Diagnostics for htMarquee.

Downloadable from the device page in Home Assistant. This exists so a
support request can start with "here is exactly what my marquee reported"
instead of a round of screenshots.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HtMarqueeConfigEntry
from .const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME

# The host stays: it is the single most useful line when someone reports
# "it stopped connecting", and it is a LAN name, not a secret.
TO_REDACT = {CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HtMarqueeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # metrics["history"] is 60 CPU + 60 RAM samples for the device's own
    # charts — noise in a diagnostics dump.
    metrics = {k: v for k, v in coordinator.metrics.items() if k != "history"}

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "tier": coordinator.tier,
        "device_sw_version": coordinator.device_sw_version,
        "version": coordinator.version,
        "status": coordinator.data,
        "hardware": coordinator.hardware,
        "metrics": metrics,
        "playlists": coordinator.playlists,
        "led_presets": coordinator.led_presets,
        # Full palettes carry a 5-colour preview each; the names are what
        # matter when a palette select shows the wrong options.
        "led_palettes": [p.get("name") for p in coordinator.led_palettes],
        "showtimes_supported": coordinator.showtimes_supported,
        "showtimes_count": len(coordinator.showtimes),
    }
