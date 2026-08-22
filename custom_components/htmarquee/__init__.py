"""The htMarquee integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import HtMarqueeApi, HtMarqueeApiError
from .const import (
    ATTR_QUERY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USE_SSL,
    CONF_USERNAME,
    DOMAIN,
    PLATFORMS,
    SERVICE_SPOTLIGHT,
)
from .coordinator import HtMarqueeCoordinator

_LOGGER = logging.getLogger(__name__)

HtMarqueeConfigEntry = ConfigEntry[HtMarqueeCoordinator]

SPOTLIGHT_SCHEMA = vol.Schema({
    vol.Required(ATTR_QUERY): cv.string,
    # Optional so single-device setups keep working unchanged; required in
    # practice once a house has two marquees.
    vol.Optional(ATTR_DEVICE_ID): cv.string,
})


async def async_setup_entry(hass: HomeAssistant, entry: HtMarqueeConfigEntry) -> bool:
    """Set up htMarquee from a config entry."""
    @callback
    def _persist_token(token: str) -> None:
        """Write a refreshed token back to the config entry.

        async_login only updates the in-memory copy, so without this every
        restart replays the stale token from storage, takes a 403, and logs
        in again. This entry has no update listener, so writing to it does
        not trigger a reload.
        """
        if entry.data.get(CONF_TOKEN) != token:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: token}
            )

    api = HtMarqueeApi(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        use_ssl=entry.data.get(CONF_USE_SSL, True),
        token=entry.data.get(CONF_TOKEN),
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        token_updated_cb=_persist_token,
    )

    coordinator = HtMarqueeCoordinator(hass, api)

    # Tier decides whether the LED/CEC/trailer entities can do anything, and
    # it has to be known *before* the platforms are set up. /api/status
    # carries it too, so this is only a head start (and a fallback for
    # firmware whose status payload predates the field).
    try:
        license_info = await api.async_get_license_status()
        coordinator.tier = license_info.get("tier", coordinator.tier)
    except HtMarqueeApiError:
        _LOGGER.debug("Could not fetch license status; tier will be read from /api/status")

    # Primes every polled group, including hardware state and the LED preset
    # list the scene platform builds its entities from.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once per domain, not per entry)
    if not hass.services.has_service(DOMAIN, SERVICE_SPOTLIGHT):
        hass.services.async_register(
            DOMAIN, SERVICE_SPOTLIGHT, _make_spotlight_handler(hass), schema=SPOTLIGHT_SCHEMA
        )

    return True


def _make_spotlight_handler(hass: HomeAssistant):
    """Build the htmarquee.spotlight handler bound to this hass instance."""

    async def handle_spotlight(call: ServiceCall) -> None:
        """Search for a movie and spotlight the top result."""
        query = call.data[ATTR_QUERY]
        coordinator = _resolve_coordinator(hass, call)

        try:
            data = await coordinator.api.async_search_movies(query)
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee search failed: {err}") from err

        results = data.get("results", [])
        if not results:
            # A typo in the title is the user's problem to see, not
            # something to bury in the log as the old handler did.
            raise ServiceValidationError(f"No movie found matching '{query}'")

        top = results[0]
        tmdb_id = top.get("tmdb_id") or top.get("id")
        _LOGGER.debug("Spotlight: '%s' -> %s (tmdb_id=%s)", query, top.get("title"), tmdb_id)
        try:
            await coordinator.api.async_manual(tmdb_id)
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee could not spotlight the movie: {err}") from err
        await coordinator.async_request_refresh()

    return handle_spotlight


def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> HtMarqueeCoordinator:
    """Pick which htMarquee device a service call is for."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if not entries:
        raise HomeAssistantError("No htMarquee device is currently set up")

    device_id = call.data.get(ATTR_DEVICE_ID)
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device_id '{device_id}'")
        for entry in entries:
            if entry.entry_id in device.config_entries:
                coordinator: HtMarqueeCoordinator = entry.runtime_data
                return coordinator
        raise ServiceValidationError("That device is not an htMarquee device")

    if len(entries) > 1:
        # Silently picking the first one was a coin flip that looked like a
        # bug from the outside.
        raise ServiceValidationError(
            "More than one htMarquee device is configured — pass device_id to choose one"
        )
    first: HtMarqueeCoordinator = entries[0].runtime_data
    return first


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
