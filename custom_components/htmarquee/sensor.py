"""Sensor platform for htMarquee."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HtMarqueeConfigEntry
from .const import DOMAIN, MANUFACTURER
from .coordinator import HtMarqueeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee sensors."""
    coordinator = entry.runtime_data
    async_add_entities([
        HtMarqueePhaseSensor(coordinator, entry),
        HtMarqueeMovieSensor(coordinator, entry),
    ])


class HtMarqueeBaseSensor(CoordinatorEntity[HtMarqueeCoordinator], SensorEntity):
    """Base sensor with shared device info."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "htMarquee",
            "manufacturer": MANUFACTURER,
            "model": "Smart Movie Poster Display",
        }


class HtMarqueePhaseSensor(HtMarqueeBaseSensor):
    """Current slideshow phase sensor."""

    _attr_name = "Slideshow Phase"
    _attr_icon = "mdi:filmstrip"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_phase"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        slideshow = self.coordinator.data.get("slideshow", {})
        return slideshow.get("phase")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        slideshow = self.coordinator.data.get("slideshow", {})
        attrs["phase_duration_s"] = slideshow.get("phase_duration_s")
        attrs["transition_effect"] = slideshow.get("transition_effect")
        attrs["is_paused"] = slideshow.get("is_paused")
        return attrs


class HtMarqueeMovieSensor(HtMarqueeBaseSensor):
    """Current movie sensor with rich metadata attributes."""

    _attr_name = "Current Movie"
    _attr_icon = "mdi:movie-open"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_movie"

    @property
    def native_value(self) -> str | None:
        movie = self._movie
        if not movie:
            return None
        return movie.get("title")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        movie = self._movie
        if not movie:
            return attrs
        attrs["tmdb_id"] = movie.get("tmdb_id")
        attrs["year"] = movie.get("year")
        attrs["genres"] = movie.get("genres", [])
        attrs["rating"] = movie.get("rating")
        attrs["runtime"] = movie.get("runtime")
        attrs["vote_average"] = movie.get("vote_average")
        attrs["rt_rating"] = movie.get("rt_rating")
        attrs["metacritic_rating"] = movie.get("metacritic_rating")
        attrs["tagline"] = movie.get("tagline")
        attrs["aspect_ratio"] = movie.get("aspect_ratio")
        poster = movie.get("poster_url", "")
        attrs["poster_url"] = self.coordinator.api.get_poster_url(poster) if poster else None
        return attrs

    @property
    def _movie(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("current_movie")
