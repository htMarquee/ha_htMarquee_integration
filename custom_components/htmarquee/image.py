"""Image platform for htMarquee.

The device's artwork cannot be linked to directly from a dashboard: every
``/assets/*`` path answers 403 without the API bearer token, and the device
presents a self-signed cert issued by its own CA whose CN does not match the
configured host. A browser hits one or both of those and draws a broken
image. These entities exist so Home Assistant fetches the bytes with the API
client's credentials and re-serves them from its own proxied
``entity_picture`` URL, which any card can render.

The media player already does exactly this for the poster via
``async_get_media_image``, but that hook only carries one image per entity.
The backdrop and the studio logo therefore need entities of their own.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HtMarqueeConfigEntry
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee images."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            HtMarqueePosterImage(hass, coordinator, entry),
            HtMarqueeBackdropImage(hass, coordinator, entry),
            HtMarqueeStudioLogoImage(hass, coordinator, entry),
        ]
    )


class HtMarqueeMovieImage(HtMarqueeEntity, ImageEntity):
    """Base for artwork that follows whatever movie is currently on screen.

    Subclasses set ``_asset_key`` to the field of ``current_movie`` (from
    /api/status) that holds the device-relative asset path.
    """

    _asset_key: str

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
        key: str,
    ) -> None:
        HtMarqueeEntity.__init__(self, coordinator, entry, key)
        # ImageEntity needs hass at construction to mint the access token
        # that its proxied URL is signed with. Its verify_ssl flag only
        # governs the httpx client it would use to fetch _attr_image_url,
        # which we never set — async_image goes through the API client
        # instead, because that is what holds the token and the cert
        # exception.
        ImageEntity.__init__(self, hass)
        self._current_path = self._asset_path
        self._attr_image_last_updated = dt_util.utcnow()

    @property
    def _asset_path(self) -> str | None:
        """Device-relative path of this entity's artwork, or None."""
        data: dict[str, Any] = self.coordinator.data or {}
        movie = data.get("current_movie") or {}
        # Normalises "" to None so the empty string can't reach
        # async_get_image and turn into a request for the device root.
        return movie.get(self._asset_key) or None

    @property
    def available(self) -> bool:
        """Unavailable while the current movie has no such artwork.

        TMDB does not carry a backdrop or a studio logo for every title.
        Reporting unavailable lets the card hide itself, which reads better
        than serving no bytes and letting the browser draw a broken image.
        """
        return super().available and self._asset_path is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Stamp a fresh timestamp whenever the artwork changes.

        The frontend caches an image entity's bytes until
        ``image_last_updated`` moves. Without this the first movie's
        backdrop would stay on screen for the rest of the slideshow.
        """
        path = self._asset_path
        if path != self._current_path:
            self._current_path = path
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Fetch the artwork through the API client (auth + self-signed cert)."""
        path = self._asset_path
        if not path:
            return None
        result = await self.coordinator.api.async_get_image(path)
        if result is None:
            return None
        content, content_type = result
        # The device serves JPEG backdrops but PNG logos, so take the type
        # from the response rather than assuming one.
        self._attr_content_type = content_type
        return content


class HtMarqueePosterImage(HtMarqueeMovieImage):
    """Portrait theatrical poster for the current movie.

    The media player serves this same artwork through its own proxy, but
    only one image at a time — this entity exists so a dashboard can show
    the poster and the backdrop side by side.
    """

    _attr_name = "Poster"
    _attr_icon = "mdi:image-frame"
    _asset_key = "poster_url"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(hass, coordinator, entry, "poster")


class HtMarqueeBackdropImage(HtMarqueeMovieImage):
    """Wide 16:9 backdrop for the current movie."""

    _attr_name = "Backdrop"
    _attr_icon = "mdi:image-area"
    _asset_key = "backdrop_url"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(hass, coordinator, entry, "backdrop")


class HtMarqueeStudioLogoImage(HtMarqueeMovieImage):
    """Distributing studio's logo for the current movie."""

    _attr_name = "Studio Logo"
    _attr_icon = "mdi:domain"
    _asset_key = "studio_logo_url"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(hass, coordinator, entry, "studio_logo")
