"""Media player platform for htMarquee."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError
from .const import SOURCE_AUTO, STATE_MAP
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee media player."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeMediaPlayer(coordinator, entry)])


class HtMarqueeMediaPlayer(HtMarqueeEntity, MediaPlayerEntity):
    """Representation of htMarquee as a media player."""

    _attr_name = None  # Use device name
    _attr_media_content_type = MediaType.MOVIE

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "media_player")

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
            # BROWSE_MEDIA is what puts the browser dialog on the card, and
            # SEARCH_MEDIA is what puts the search box inside it. PLAY_MEDIA
            # is how the frontend hands a picked result back to us.
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.SEARCH_MEDIA
            | MediaPlayerEntityFeature.PLAY_MEDIA
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
        # Any state the device reports that we don't recognise falls back to
        # "off" — that used to be a real OFFLINE state, which the device
        # dropped in the LED release, so today this only catches drift.
        htm_state = self.coordinator.data.get("state", "")
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
    def _artwork_path(self) -> str | None:
        """Device-relative path of the art the media card should show.

        The poster is the identity of the title and is what the media card
        should lead with. The backdrop was tried here and looked wrong: the
        card renders art as a small thumbnail plus a colour-extracted
        background, so a 16:9 still ends up cropped to an unreadable strip.
        The backdrop is available on its own image entity for anyone who
        wants it full width.

        Fall back to the backdrop only if a title somehow has no poster.
        """
        movie = self._current_movie or {}
        return movie.get("poster_url") or movie.get("backdrop_url") or None

    @property
    def media_image_url(self) -> str | None:
        """Return artwork URL for the current movie."""
        art = self._artwork_path
        # get_poster_url is a generic path -> absolute URL joiner despite
        # the name; it predates there being more than one kind of artwork.
        return self.coordinator.api.get_poster_url(art) if art else None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Artwork is on the local network, HA needs to proxy it."""
        return False

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Fetch artwork via API client (handles auth + self-signed cert)."""
        art = self._artwork_path
        if not art:
            return None, None
        result = await self.coordinator.api.async_get_image(art)
        if result:
            return result
        return None, None

    @property
    def source(self) -> str | None:
        """Return active playlist name."""
        slideshow = self.coordinator.data.get("slideshow", {}) if self.coordinator.data else {}
        playlist_id = slideshow.get("playlist_id")
        if not playlist_id:
            return SOURCE_AUTO
        for pl in self.coordinator.playlists:
            if pl.get("id") == playlist_id:
                return pl.get("name", f"Playlist {playlist_id}")
        return f"Playlist {playlist_id}"

    @property
    def source_list(self) -> list[str]:
        """Return list of available playlists."""
        sources = [SOURCE_AUTO]
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
        if source == SOURCE_AUTO:
            await self.coordinator.api.async_deactivate_playlist()
        else:
            for pl in self.coordinator.playlists:
                if pl.get("name") == source:
                    await self.coordinator.api.async_activate_playlist(pl["id"])
                    break
        await self.coordinator.async_request_refresh()

    # ── Search & browse ─────────────────────────────────────────────────
    #
    # These three methods are what turn "spotlight a movie" from a service
    # call that needs the exact title into a search box with a grid of
    # posters to pick from. The frontend drives all of it: browse gives the
    # dialog a root to open, search fills it with results, and play hands
    # the chosen item back.

    # media_content_id has to survive a round trip through the frontend as
    # an opaque string, so both kinds carry their own prefix rather than
    # relying on media_content_type to disambiguate them.
    _MOVIE_PREFIX = "movie:"
    _PLAYLIST_PREFIX = "playlist:"

    # TMDB serves poster thumbnails publicly over a valid cert, so search
    # results can link them directly. The device's own /assets copies could
    # not be used here: they 403 without the bearer token, and the movie may
    # not be cached on the device yet at search time anyway.
    _TMDB_THUMB_BASE = "https://image.tmdb.org/t/p/w342"

    def _movie_to_browse_item(self, movie: dict[str, Any]) -> BrowseMedia:
        """Turn one /api/movie/search hit into a media-browser entry."""
        title = movie.get("title") or "Untitled"
        # release_date is a full ISO date; the year alone disambiguates
        # remakes, which is the whole reason a picker beats "top result".
        year = (movie.get("release_date") or "")[:4]
        poster_path = movie.get("poster_path")
        return BrowseMedia(
            media_class=MediaClass.MOVIE,
            media_content_id=f"{self._MOVIE_PREFIX}{movie.get('id')}",
            media_content_type=MediaType.MOVIE,
            title=f"{title} ({year})" if year else title,
            can_play=True,
            can_expand=False,
            thumbnail=f"{self._TMDB_THUMB_BASE}{poster_path}" if poster_path else None,
        )

    def _playlist_to_browse_item(self, playlist: dict[str, Any]) -> BrowseMedia:
        """Turn one configured playlist into a media-browser entry."""
        return BrowseMedia(
            media_class=MediaClass.PLAYLIST,
            media_content_id=f"{self._PLAYLIST_PREFIX}{playlist.get('id')}",
            media_content_type=MediaType.PLAYLIST,
            title=playlist.get("name") or f"Playlist {playlist.get('id')}",
            can_play=True,
            # The API exposes playlists but not their contents, so there is
            # nothing to drill into.
            can_expand=False,
        )

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Search the movie catalogue by title."""
        # The frontend can ask for a subset of classes; movies are all we
        # return, so an explicit filter that excludes them means no results
        # rather than an unfiltered list.
        if query.media_filter_classes and MediaClass.MOVIE not in query.media_filter_classes:
            return SearchMedia(result=[])

        try:
            data = await self.coordinator.api.async_search_movies(query.search_query)
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee search failed: {err}") from err

        results = data.get("results") or []
        return SearchMedia(result=[self._movie_to_browse_item(m) for m in results])

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Return the browsable root: the device's playlists.

        There is no tree to walk — nothing here expands — but a root is
        required before the frontend will offer the dialog that hosts the
        search box, and listing the playlists makes the trip worthwhile.
        """
        if media_content_id is not None and media_content_id != self._PLAYLIST_PREFIX:
            # Every child is can_expand=False, so this only fires if the
            # frontend asks for something we never handed it.
            raise HomeAssistantError(f"htMarquee cannot browse '{media_content_id}'")

        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id=self._PLAYLIST_PREFIX,
            media_content_type=MediaType.PLAYLIST,
            title="htMarquee",
            can_play=False,
            can_expand=True,
            can_search=True,
            search_media_classes=[MediaClass.MOVIE],
            children_media_class=MediaClass.PLAYLIST,
            children=[self._playlist_to_browse_item(pl) for pl in self.coordinator.playlists],
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Spotlight a picked movie, or activate a picked playlist."""
        try:
            if media_id.startswith(self._MOVIE_PREFIX):
                tmdb_id = int(media_id.removeprefix(self._MOVIE_PREFIX))
                await self.coordinator.api.async_manual(tmdb_id)
            elif media_id.startswith(self._PLAYLIST_PREFIX):
                playlist_id = int(media_id.removeprefix(self._PLAYLIST_PREFIX))
                await self.coordinator.api.async_activate_playlist(playlist_id)
            else:
                raise HomeAssistantError(
                    f"htMarquee cannot play '{media_id}' — expected a movie or playlist"
                )
        except ValueError as err:
            # A prefix with a non-numeric id behind it: malformed, not a
            # device failure, so say so rather than surfacing int()'s message.
            raise HomeAssistantError(f"htMarquee got a malformed media id '{media_id}'") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee could not play the selection: {err}") from err

        await self.coordinator.async_request_refresh()
