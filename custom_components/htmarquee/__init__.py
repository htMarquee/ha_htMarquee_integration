"""The htMarquee integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .api import HtMarqueeApi, HtMarqueeApiError
from .const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_TOKEN, CONF_USE_SSL, CONF_USERNAME, DOMAIN, PLATFORMS
from .coordinator import HtMarqueeCoordinator

_LOGGER = logging.getLogger(__name__)

HtMarqueeConfigEntry = ConfigEntry[HtMarqueeCoordinator]

SERVICE_SPOTLIGHT = "spotlight"
ATTR_QUERY = "query"

SPOTLIGHT_SCHEMA = vol.Schema({
    vol.Required(ATTR_QUERY): str,
})


async def async_setup_entry(hass: HomeAssistant, entry: HtMarqueeConfigEntry) -> bool:
    """Set up htMarquee from a config entry."""
    api = HtMarqueeApi(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        use_ssl=entry.data.get(CONF_USE_SSL, True),
        token=entry.data.get(CONF_TOKEN),
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
    )

    coordinator = HtMarqueeCoordinator(hass, api)

    # Fetch initial license tier and device version before first status poll
    try:
        license_info = await api.async_get_license_status()
        coordinator.tier = license_info.get("tier", coordinator.tier)
    except HtMarqueeApiError:
        _LOGGER.debug("Could not fetch license status; tier will be read from /api/status")

    try:
        update_status = await api.async_get_system_update_status()
        coordinator.device_sw_version = update_status.get("version")
    except HtMarqueeApiError:
        _LOGGER.debug("Could not fetch system version")

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once per domain, not per entry)
    if not hass.services.has_service(DOMAIN, SERVICE_SPOTLIGHT):

        async def handle_spotlight(call: ServiceCall) -> None:
            """Search for a movie and spotlight the top result."""
            query = call.data[ATTR_QUERY]

            # Use the first config entry's coordinator
            entries = hass.config_entries.async_entries(DOMAIN)
            if not entries:
                _LOGGER.error("No htMarquee integration configured")
                return

            coord: HtMarqueeCoordinator = entries[0].runtime_data
            try:
                data = await coord.api.async_search_movies(query)
                results = data.get("results", [])
                if not results:
                    _LOGGER.warning("Spotlight: no results for '%s'", query)
                    return

                top = results[0]
                tmdb_id = top.get("tmdb_id") or top.get("id")
                title = top.get("title", "Unknown")
                _LOGGER.info("Spotlight: '%s' → %s (tmdb_id=%s)", query, title, tmdb_id)
                await coord.api.async_manual(tmdb_id)
                await coord.async_request_refresh()
            except HtMarqueeApiError as err:
                _LOGGER.error("Spotlight failed: %s", err)

        hass.services.async_register(
            DOMAIN, SERVICE_SPOTLIGHT, handle_spotlight, schema=SPOTLIGHT_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HtMarqueeConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HtMarqueeCoordinator = entry.runtime_data
        await coordinator.api.close()

    # Unregister services if no entries remain
    entries = hass.config_entries.async_entries(DOMAIN)
    remaining = [e for e in entries if e.entry_id != entry.entry_id]
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_SPOTLIGHT)

    return unload_ok
