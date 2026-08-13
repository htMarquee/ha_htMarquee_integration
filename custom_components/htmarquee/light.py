"""Light platform for the htMarquee LED strip."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtMarqueeConfigEntry
from .api import HtMarqueeApiError, HtMarqueePremiumRequired
from .const import (
    ATTR_PALETTE,
    ATTR_SPEED,
    LABEL_TO_LED_EFFECT,
    LED_EFFECT_LABELS,
    LED_EFFECTS,
    PALETTE_COLOR_PICKER,
    SERVICE_LED_EFFECT,
    palette_from_label,
)
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee LED light."""
    coordinator = entry.runtime_data
    async_add_entities([HtMarqueeLedLight(coordinator, entry)])

    # An entity service, not a domain service: it targets the light itself,
    # so it works unchanged with two htMarquee devices in one house.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_LED_EFFECT,
        {
            vol.Required(ATTR_EFFECT): cv.string,
            vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            vol.Optional(ATTR_PALETTE): cv.string,
        },
        "async_apply_led_effect",
    )


class HtMarqueeLedLight(HtMarqueeLedEntity, LightEntity):
    """LED strip controlled via the htMarquee API."""

    _attr_name = "LED Strip"
    _attr_icon = "mdi:led-strip-variant"
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        coordinator: HtMarqueeCoordinator,
        entry: HtMarqueeConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "led")

    @property
    def _led(self) -> dict[str, Any]:
        return self.coordinator.led

    @property
    def is_on(self) -> bool | None:
        return self._led.get("on")

    @property
    def brightness(self) -> int | None:
        """Return 0-255 brightness."""
        return self._led.get("brightness")

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        color = self._led.get("color")
        if isinstance(color, list) and len(color) == 3:
            return (color[0], color[1], color[2])
        return None

    @property
    def effect(self) -> str | None:
        name = self._led.get("effect_name")
        if not name:
            return None
        return LED_EFFECTS.get(name, name)

    @property
    def effect_list(self) -> list[str]:
        """Effect labels the device understands.

        If the device reports an effect this integration has never heard of
        — firmware newer than the integration — it is appended verbatim.
        Home Assistant logs a warning for an ``effect`` outside
        ``effect_list``, and the honest fix is to widen the list rather than
        pretend the strip is doing something else.
        """
        current = self._led.get("effect_name")
        if current and current not in LED_EFFECTS:
            return [*LED_EFFECT_LABELS, current]
        return LED_EFFECT_LABELS

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        led = self._led
        return {
            "speed": led.get("speed"),
            "palette": led.get("palette_name"),
            "led_count": led.get("led_count"),
            "follow_display_state": led.get("follow_display_state"),
        }

    # ── Controls ────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the strip, optionally setting effect, colour, brightness."""
        led = self._led
        api = self.coordinator.api

        requested_effect: str | None = None
        if ATTR_EFFECT in kwargs:
            label = kwargs[ATTR_EFFECT]
            # Unknown labels pass through so a raw device name (or a brand
            # new firmware effect) still reaches the device, which validates.
            requested_effect = LABEL_TO_LED_EFFECT.get(label, label)

        effect = requested_effect or self.coordinator.led_effect_name
        speed = self.coordinator.led_speed
        palette = led.get("palette_name") or PALETTE_COLOR_PICKER
        needs_effect_call = requested_effect is not None

        try:
            # /api/led/color and /api/led/effect both power the strip on
            # device-side. Only reach for /api/led/power when neither will
            # run, so turning on *with* a colour or effect doesn't flash the
            # previous look first.
            if not led.get("on") and not needs_effect_call and ATTR_RGB_COLOR not in kwargs:
                await api.async_led_power(True)

            if ATTR_RGB_COLOR in kwargs:
                r, g, b = kwargs[ATTR_RGB_COLOR]
                await api.async_led_color(r, g, b)
                # A running effect in palette mode ignores the picker colour
                # entirely, so `rgb_color` would silently do nothing. Pin the
                # strip to the picker; `solid` already paints the picker
                # colour directly and needs no pinning.
                if effect != "solid" and palette != PALETTE_COLOR_PICKER:
                    palette = PALETTE_COLOR_PICKER
                    needs_effect_call = True

            if needs_effect_call:
                await api.async_led_effect(effect, speed, palette)

            if ATTR_BRIGHTNESS in kwargs:
                await api.async_led_brightness(kwargs[ATTR_BRIGHTNESS])
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee rejected the LED command: {err}") from err

        await self.coordinator.async_refresh_hardware()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off LED strip."""
        try:
            await self.coordinator.api.async_led_power(False)
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        await self.coordinator.async_refresh_hardware()

    async def async_apply_led_effect(
        self, effect: str, speed: int | None = None, palette: str | None = None
    ) -> None:
        """`htmarquee.led_effect` — set effect, speed and palette at once.

        Every one of those changes restarts the running effect on the device,
        so setting them through three separate entities produces three
        visible restarts. This sends them as a single call.
        """
        name = LABEL_TO_LED_EFFECT.get(effect, effect)
        known = [p.get("name", "") for p in self.coordinator.led_palettes]
        resolved_palette = palette_from_label(palette, known) if palette else None
        try:
            await self.coordinator.api.async_led_effect(
                name,
                speed if speed is not None else self.coordinator.led_speed,
                resolved_palette,
            )
        except HtMarqueePremiumRequired as err:
            raise HomeAssistantError("LED control requires htMarquee Premiere tier") from err
        except HtMarqueeApiError as err:
            raise HomeAssistantError(f"htMarquee rejected the LED command: {err}") from err
        await self.coordinator.async_refresh_hardware()
