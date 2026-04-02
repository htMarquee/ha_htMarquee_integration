"""Media player platform for htMarquee."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HtMarqueeConfigEntry
from .const import DOMAIN, MANUFACTURER, STATE_MAP
from .coordinator import HtMarqueeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee media player."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeMediaPlayer(coordinator, entry)])


class HtMarqueeMediaPlayer(CoordinatorEntity[HtMarqueeCoordinator], MediaPlayerEntity):
    """Representation of htMarquee as a media player."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_media_content_type = MediaType.MOVIE

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media_player"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info with sw_version from coordinator."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "htMarquee",
            "manufacturer": MANUFACTURER,
            "model": "Smart Movie Poster Display",
            "sw_version": self.coordinator.device_sw_version,
        }

    @property
    def _is_external_source(self) -> bool:
        """Return True when an external app (e.g. Plex) is driving htMarquee."""
        if not self.coordinator.data:
            return False
        label = self.coordinator.data.get("state_label", "")
        return label.startswith("Playing on ")

    @property
    def _external_source_name(self) -> str | None:
        """Return the external source name (e.g. 'Plex'), or None."""
        if not self.coordinator.data:
            return None
        label = self.coordinator.data.get("state_label", "")
        if label.startswith("Playing on "):
            return label[len("Playing on "):]
        return None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features, hiding playback controls during external source."""
        if self._is_external_source:
            return MediaPlayerEntityFeature.SELECT_SOURCE
        return (
            MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def app_name(self) -> str | None:
        """Return the external app name when one is controlling htMarquee."""
        return self._external_source_name

    @property
    def state(self) -> MediaPlayerState | None:
        """Return current state."""
        if not self.coordinator.data:
            return None
        htm_state = self.coordinator.data.get("state", "OFFLINE")
        slideshow = self.coordinator.data.get("slideshow", {})
        is_paused = slideshow.get("is_paused", False)

        if self._is_external_source:
            return MediaPlayerState.ON
        if htm_state == "IDLE" and is_paused:
            return MediaPlayerState.PAUSED
        return MediaPlayerState(STATE_MAP.get(htm_state, "off"))

    @property
    def media_title(self) -> str | None:
        """Return current movie title."""
        movie = self._current_movie
        if not movie:
            return None
        title = movie.get("title", "")
        year = movie.get("year")
        return f"{title} ({year})" if year else title

    @property
    def media_image_url(self) -> str | None:
        """Return poster URL for the current movie."""
        movie = self._current_movie
        if not movie:
            return None
        poster = movie.get("poster_url", "")
        return self.coordinator.api.get_poster_url(poster) if poster else None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Poster is on the local network, HA needs to proxy it."""
        return False

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Fetch poster via API client (handles self-signed cert)."""
        movie = self._current_movie
        if not movie:
            return None, None
        poster = movie.get("poster_url", "")
        if not poster:
            return None, None
        result = await self.coordinator.api.async_get_image(poster)
        if result:
            return result
        return None, None

    @property
    def source(self) -> str | None:
        """Return active playlist name."""
        slideshow = self.coordinator.data.get("slideshow", {}) if self.coordinator.data else {}
        playlist_id = slideshow.get("playlist_id")
        if not playlist_id:
            return "Auto (Upcoming)"
        for pl in self.coordinator.playlists:
            if pl.get("id") == playlist_id:
                return pl.get("name", f"Playlist {playlist_id}")
        return f"Playlist {playlist_id}"

    @property
    def source_list(self) -> list[str]:
        """Return list of available playlists."""
        sources = ["Auto (Upcoming)"]
        for pl in self.coordinator.playlists:
            name = pl.get("name")
            if name:
                sources.append(name)
        return sources

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        attrs: dict[str, Any] = {}
        movie = self._current_movie
        if movie:
            attrs["tmdb_id"] = movie.get("tmdb_id")
            attrs["genres"] = movie.get("genres", [])
            attrs["rating"] = movie.get("rating")
            attrs["runtime"] = movie.get("runtime")
            attrs["vote_average"] = movie.get("vote_average")
            attrs["rt_rating"] = movie.get("rt_rating")
            attrs["metacritic_rating"] = movie.get("metacritic_rating")
            attrs["tagline"] = movie.get("tagline")

        slideshow = self.coordinator.data.get("slideshow", {}) if self.coordinator.data else {}
        attrs["phase"] = slideshow.get("phase")
        attrs["current_index"] = slideshow.get("current_index")
        attrs["total_items"] = slideshow.get("total_items")

        if self.coordinator.data:
            attrs["state_label"] = self.coordinator.data.get("state_label")

        return attrs

    @property
    def _current_movie(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("current_movie")

    # ── Controls ────────────────────────────────────────────────────────

    async def async_media_play(self) -> None:
        """Resume slideshow or exit spotlight."""
        data = self.coordinator.data or {}
        if data.get("state") == "MANUAL":
            await self.coordinator.api.async_resume()
        else:
            # Unpause
            slideshow = data.get("slideshow", {})
            if slideshow.get("is_paused"):
                await self.coordinator.api.async_pause()  # toggle
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        """Pause slideshow."""
        await self.coordinator.api.async_pause()
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        """Skip to next movie."""
        await self.coordinator.api.async_skip()
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        """Go to previous movie."""
        await self.coordinator.api.async_previous()
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        """Activate a playlist by name."""
        if source == "Auto (Upcoming)":
            await self.coordinator.api.async_deactivate_playlist()
        else:
            for pl in self.coordinator.playlists:
                if pl.get("name") == source:
                    await self.coordinator.api.async_activate_playlist(pl["id"])
                    break
        await self.coordinator.async_request_refresh()
