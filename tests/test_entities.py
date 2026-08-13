"""Entity behaviour against real htMarquee API payloads.

Requires `homeassistant` to be importable (`pip install homeassistant`); it
does not need a running Home Assistant. Entities are built directly against a
coordinator whose state is set by hand, so the only thing faked is the HTTP
client — the true unreachable boundary. Everything under test is the real
entity code.

    python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

pytest.importorskip("homeassistant", reason="needs `pip install homeassistant`")

from custom_components.htmarquee.const import (  # noqa: E402
    LED_EFFECT_LABELS,
    PALETTE_COLOR_PICKER,
)
from custom_components.htmarquee.coordinator import HtMarqueeCoordinator  # noqa: E402
from custom_components.htmarquee.light import HtMarqueeLedLight  # noqa: E402
from custom_components.htmarquee.number import HtMarqueeLedSpeedNumber  # noqa: E402
from custom_components.htmarquee.scene import HtMarqueeLedPresetScene  # noqa: E402
from custom_components.htmarquee.select import HtMarqueeLedPaletteSelect  # noqa: E402
from custom_components.htmarquee.sensor import HtMarqueeNextShowtimeSensor  # noqa: E402
from custom_components.htmarquee.switch import (  # noqa: E402
    HtMarqueeFollowStateSwitch,
    HtMarqueeTvSwitch,
)
from custom_components.htmarquee.update import HtMarqueeUpdate  # noqa: E402

# Verbatim shape of GET /api/hardware/status on a Premiere device with the
# strip running Car Chase off the cinema palette.
HARDWARE: dict[str, Any] = {
    "platform": "rpi",
    "led_enabled": True,
    "cec_enabled": True,
    "led": {
        "on": True,
        "brightness": 180,
        "color": [255, 200, 150],
        "effect": 101,
        "effect_name": "car_chase",
        "speed": 128,
        "palette_name": "cinema",
        "led_count": 251,
        "follow_display_state": False,
    },
    "cec": {
        "tv_power": True,
        "tv_power_label": "on",
        "is_active_source": True,
        "osd_name": "SAMSUNG",
        "hdmi_port": 1,
    },
    "display": {"connector": "HDMI-1", "resolution": "3840x2160", "refresh_rate": "60.00"},
}

PALETTES = [
    {"name": "default", "colors": [], "type": "built-in"},
    {"name": "warm_white", "colors": [], "type": "built-in"},
    {"name": "cinema", "colors": [], "type": "built-in"},
    {"name": "Bond Villain", "colors": [], "type": "custom"},
]


class FakeApi:
    """Records calls instead of making them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.base_url = "https://htmarquee.local:443"

    def _record(self, name: str, *args: Any) -> Any:
        async def _call() -> dict[str, Any]:
            self.calls.append((name, args))
            return {"status": "ok"}

        return _call()

    def async_led_power(self, state: bool):
        return self._record("power", state)

    def async_led_brightness(self, brightness: int):
        return self._record("brightness", brightness)

    def async_led_color(self, r: int, g: int, b: int):
        return self._record("color", r, g, b)

    def async_led_effect(self, effect: str, speed: int, palette: str | None = None):
        return self._record("effect", effect, speed, palette)

    def async_led_follow_state(self, enabled: bool):
        return self._record("follow_state", enabled)

    def async_apply_led_preset(self, preset_id: int):
        return self._record("apply_preset", preset_id)

    def async_cec_power(self, command: str):
        return self._record("cec", command)

    def async_check_update(self):
        return self._record("check_update")

    def async_install_update(self):
        return self._record("install_update")

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class FakeEntry:
    entry_id = "test_entry"


def make_coordinator(**overrides: Any) -> HtMarqueeCoordinator:
    """A real coordinator with hand-set state and no Home Assistant.

    __init__ is skipped deliberately: it only wires up polling machinery that
    needs a `hass`, while every property under test reads plain attributes.
    """
    coordinator = object.__new__(HtMarqueeCoordinator)
    coordinator.api = FakeApi()
    coordinator.hardware = dict(HARDWARE)
    coordinator.metrics = {}
    coordinator.version = {}
    coordinator.playlists = []
    coordinator.led_presets = []
    coordinator.led_palettes = list(PALETTES)
    coordinator.showtimes = []
    coordinator.showtimes_supported = True
    coordinator.tier = "premiere"
    coordinator.device_sw_version = "1.4.3"
    coordinator.data = {}
    coordinator.last_update_success = True

    async def _refresh_hardware() -> None:
        return None

    coordinator.async_refresh_hardware = _refresh_hardware  # type: ignore[method-assign]
    coordinator.async_request_refresh = _refresh_hardware  # type: ignore[method-assign]

    for key, value in overrides.items():
        setattr(coordinator, key, value)
    return coordinator


def make_light(**overrides: Any) -> tuple[HtMarqueeLedLight, FakeApi]:
    coordinator = make_coordinator(**overrides)
    return HtMarqueeLedLight(coordinator, FakeEntry()), coordinator.api


# ── Wiring ──────────────────────────────────────────────────────────────


def test_every_declared_platform_has_a_module_that_imports():
    """Home Assistant only discovers a platform's import error at setup time,
    where it shows up as a broken integration rather than a stack trace. This
    is the cheapest place to catch a bad import path."""
    import importlib

    from custom_components.htmarquee.const import PLATFORMS

    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.htmarquee.{platform.value}")
        assert hasattr(module, "async_setup_entry"), f"{platform.value} has no async_setup_entry"

    # Not platforms, but equally load-bearing and equally silent when broken.
    importlib.import_module("custom_components.htmarquee.config_flow")
    diagnostics = importlib.import_module("custom_components.htmarquee.diagnostics")
    assert hasattr(diagnostics, "async_get_config_entry_diagnostics")


def test_diagnostics_redacts_credentials_and_drops_metric_history():
    from custom_components.htmarquee.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    class Entry:
        entry_id = "test_entry"
        title = "htMarquee (htmarquee.local)"
        data = {
            "host": "htmarquee.local",
            "port": 443,
            "username": "admin",
            "password": "1234",
            "token": "eyJhbGciOi",
        }
        runtime_data = None

    entry = Entry()
    entry.runtime_data = make_coordinator(
        metrics={"cpu_percent": 12.0, "history": {"cpu": [1] * 60, "ram": [2] * 60}}
    )
    report = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert report["entry"]["data"]["host"] == "htmarquee.local"  # kept: needed for support
    for secret in ("password", "token", "username"):
        assert report["entry"]["data"][secret] == "**REDACTED**"
    assert "history" not in report["metrics"]
    assert report["metrics"]["cpu_percent"] == 12.0


# ── Coordinator ─────────────────────────────────────────────────────────


def test_led_substate_is_a_dict_when_the_strip_is_disabled():
    """/api/hardware/status sends `"led": null` when the LED service is off.

    A plain .get("led", {}) hands back None there, and every reader then
    trips over None.get — which is reachable because Home Assistant still
    computes capability attributes for unavailable entities.
    """
    coordinator = make_coordinator(hardware={"led_enabled": False, "led": None, "cec": None})
    assert coordinator.led == {}
    assert coordinator.cec == {}
    assert coordinator.led_enabled is False

    light = HtMarqueeLedLight(coordinator, FakeEntry())
    assert light.is_on is None
    assert light.rgb_color is None
    assert light.effect is None
    assert light.available is False


# ── Light ───────────────────────────────────────────────────────────────


def test_effect_list_covers_every_device_effect():
    light, _ = make_light()
    assert len(LED_EFFECT_LABELS) == 26
    assert light.effect_list == LED_EFFECT_LABELS
    assert light.effect == "Car Chase"


def test_unknown_firmware_effect_is_surfaced_not_hidden():
    """A newer device reporting an effect we've never heard of must still
    produce an `effect` that is inside `effect_list`, or HA logs a warning
    and the UI shows a value it considers invalid."""
    hardware = {**HARDWARE, "led": {**HARDWARE["led"], "effect_name": "disco_inferno"}}
    light, _ = make_light(hardware=hardware)
    assert light.effect == "disco_inferno"
    assert light.effect in light.effect_list


def test_setting_a_colour_pins_the_palette_to_the_picker():
    """In palette mode the strip ignores the picked colour, so an rgb_color
    request would silently do nothing without this."""
    light, api = make_light()
    asyncio.run(light.async_turn_on(rgb_color=(10, 20, 30)))

    assert api.names == ["color", "effect"]
    assert api.calls[0] == ("color", (10, 20, 30))
    # Effect and speed carry over unchanged; only the palette moves.
    assert api.calls[1] == ("effect", ("car_chase", 128, PALETTE_COLOR_PICKER))


def test_colour_on_solid_needs_no_palette_pinning():
    """`solid` paints the picked colour directly — a second call would just
    restart it for nothing."""
    hardware = {
        **HARDWARE,
        "led": {**HARDWARE["led"], "effect_name": "solid", "palette_name": "default"},
    }
    light, api = make_light(hardware=hardware)
    asyncio.run(light.async_turn_on(rgb_color=(1, 2, 3)))
    assert api.names == ["color"]


def test_colour_while_already_on_the_picker_does_not_restart_the_effect():
    hardware = {
        **HARDWARE,
        "led": {**HARDWARE["led"], "palette_name": PALETTE_COLOR_PICKER},
    }
    light, api = make_light(hardware=hardware)
    asyncio.run(light.async_turn_on(rgb_color=(1, 2, 3)))
    assert api.names == ["color"]


def test_turning_on_with_an_effect_skips_the_power_call():
    """/api/led/effect powers the strip on device-side. Calling power first
    would flash the previous effect before the requested one starts."""
    hardware = {**HARDWARE, "led": {**HARDWARE["led"], "on": False}}
    light, api = make_light(hardware=hardware)
    asyncio.run(light.async_turn_on(effect="Spotlight - Premiere Night"))

    assert api.names == ["effect"]
    assert api.calls[0] == ("effect", ("premiere_night", 128, "cinema"))


def test_turning_on_bare_uses_the_power_endpoint():
    hardware = {**HARDWARE, "led": {**HARDWARE["led"], "on": False}}
    light, api = make_light(hardware=hardware)
    asyncio.run(light.async_turn_on())
    assert api.calls == [("power", (True,))]


def test_brightness_is_applied_after_the_effect_restart():
    light, api = make_light()
    asyncio.run(light.async_turn_on(effect="Red Carpet", brightness=42))
    assert api.names == ["effect", "brightness"]
    assert api.calls[-1] == ("brightness", (42,))


def test_led_effect_service_sends_one_call():
    light, api = make_light()
    asyncio.run(light.async_apply_led_effect(effect="Corner Flames", speed=150, palette="Ocean"))
    # "Ocean" isn't on this device, so it passes through untouched and the
    # device decides — a custom palette must survive the round trip verbatim.
    assert api.calls == [("effect", ("corner_fire", 150, "Ocean"))]


def test_led_effect_service_resolves_a_known_palette_label():
    light, api = make_light()
    asyncio.run(light.async_apply_led_effect(effect="Solid", palette="Bond Villain"))
    assert api.calls == [("effect", ("solid", 128, "Bond Villain"))]


def test_led_effect_service_keeps_the_current_speed_when_unset():
    light, api = make_light()
    asyncio.run(light.async_apply_led_effect(effect="Wipe"))
    assert api.calls == [("effect", ("wipe", 128, None))]


def test_speed_zero_is_preserved_not_treated_as_missing():
    """0 is the slow end of a legal 0-255 range, not "unset". A truthiness
    fallback here would snap a deliberately slow strip back to 128 on the
    next colour or palette change."""
    hardware = {**HARDWARE, "led": {**HARDWARE["led"], "speed": 0}}
    coordinator = make_coordinator(hardware=hardware)
    assert coordinator.led_speed == 0

    light = HtMarqueeLedLight(coordinator, FakeEntry())
    asyncio.run(light.async_turn_on(rgb_color=(1, 2, 3)))
    assert coordinator.api.calls[-1] == ("effect", ("car_chase", 0, PALETTE_COLOR_PICKER))


def test_missing_speed_falls_back_to_the_middle_of_the_slider():
    hardware = {**HARDWARE, "led": {k: v for k, v in HARDWARE["led"].items() if k != "speed"}}
    assert make_coordinator(hardware=hardware).led_speed == 128


def test_turn_off_powers_down():
    light, api = make_light()
    asyncio.run(light.async_turn_off())
    assert api.calls == [("power", (False,))]


# ── Select / Number ─────────────────────────────────────────────────────


def test_palette_options_lead_with_the_colour_picker():
    coordinator = make_coordinator()
    select = HtMarqueeLedPaletteSelect(coordinator, FakeEntry())
    assert select.options == ["Color Picker", "Default", "Warm White", "Cinema", "Bond Villain"]
    assert select.current_option == "Cinema"


def test_palette_deleted_on_the_device_reports_unknown():
    hardware = {**HARDWARE, "led": {**HARDWARE["led"], "palette_name": "gone"}}
    select = HtMarqueeLedPaletteSelect(make_coordinator(hardware=hardware), FakeEntry())
    assert select.current_option is None


def test_selecting_a_palette_keeps_effect_and_speed():
    coordinator = make_coordinator()
    select = HtMarqueeLedPaletteSelect(coordinator, FakeEntry())
    asyncio.run(select.async_select_option("Warm White"))
    assert coordinator.api.calls == [("effect", ("car_chase", 128, "warm_white"))]


def test_selecting_the_colour_picker_sends_the_raw_name():
    coordinator = make_coordinator()
    select = HtMarqueeLedPaletteSelect(coordinator, FakeEntry())
    asyncio.run(select.async_select_option("Color Picker"))
    assert coordinator.api.calls == [("effect", ("car_chase", 128, "color_picker"))]


def test_speed_number_keeps_effect_and_palette():
    coordinator = make_coordinator()
    number = HtMarqueeLedSpeedNumber(coordinator, FakeEntry())
    assert number.native_value == 128.0
    asyncio.run(number.async_set_native_value(200))
    assert coordinator.api.calls == [("effect", ("car_chase", 200, "cinema"))]


# ── Scene ───────────────────────────────────────────────────────────────


def test_preset_scene_tracks_renames_and_deletion():
    preset = {"id": 7, "name": "Movie Night", "playlist_id": 3, "effect": "red_carpet",
              "palette": "default", "power": True}
    coordinator = make_coordinator(led_presets=[preset])
    scene = HtMarqueeLedPresetScene(coordinator, FakeEntry(), preset)

    assert scene.name == "LED Movie Night"
    assert scene.available is True
    assert scene.extra_state_attributes["playlist_id"] == 3

    coordinator.led_presets = [{**preset, "name": "Premiere"}]
    assert scene.name == "LED Premiere"

    # Deleted on the device: the scene goes unavailable rather than
    # disappearing and taking automation references with it.
    coordinator.led_presets = []
    assert scene.available is False
    assert scene.name == "LED Premiere"

    asyncio.run(scene.async_activate())
    assert coordinator.api.calls == [("apply_preset", (7,))]


# ── Switches ────────────────────────────────────────────────────────────


def test_tv_switch_reports_unknown_rather_than_guessing():
    hardware = {**HARDWARE, "cec": {"tv_power": None, "tv_power_label": "unknown"}}
    switch = HtMarqueeTvSwitch(make_coordinator(hardware=hardware), FakeEntry())
    assert switch.is_on is None
    assert switch.available is True


def test_tv_switch_sends_cec_commands():
    coordinator = make_coordinator()
    switch = HtMarqueeTvSwitch(coordinator, FakeEntry())
    assert switch.is_on is True
    switch._schedule_settle_refresh = lambda: None  # no event loop here
    asyncio.run(switch.async_turn_off())
    assert coordinator.api.calls == [("cec", ("off",))]


def test_tv_switch_unavailable_without_a_cec_adapter():
    hardware = {**HARDWARE, "cec_enabled": False, "cec": None}
    switch = HtMarqueeTvSwitch(make_coordinator(hardware=hardware), FakeEntry())
    assert switch.available is False


def test_follow_state_switch_round_trip():
    coordinator = make_coordinator()
    switch = HtMarqueeFollowStateSwitch(coordinator, FakeEntry())
    assert switch.is_on is False
    asyncio.run(switch.async_turn_on())
    assert coordinator.api.calls == [("follow_state", (True,))]


def test_led_entities_are_unavailable_on_matinee():
    coordinator = make_coordinator(tier="matinee")
    assert HtMarqueeLedPaletteSelect(coordinator, FakeEntry()).available is False
    assert HtMarqueeFollowStateSwitch(coordinator, FakeEntry()).available is False


# ── Update ──────────────────────────────────────────────────────────────


def test_up_to_date_reports_latest_equal_to_installed():
    version = {"version": "1.4.3", "slot": "a", "state": "idle", "update_available": None}
    entity = HtMarqueeUpdate(make_coordinator(version=version), FakeEntry())
    assert entity.installed_version == "1.4.3"
    assert entity.latest_version == "1.4.3"
    assert entity.in_progress is False


def test_available_update_is_offered_with_its_changelog():
    version = {
        "version": "1.4.3",
        "state": "idle",
        "update_available": {
            "version": "1.4.4",
            "changelog": "x" * 400,
            "released_at": "2026-08-13",
            "size_bytes": 1234,
        },
    }
    entity = HtMarqueeUpdate(make_coordinator(version=version), FakeEntry())
    assert entity.latest_version == "1.4.4"
    assert len(entity.release_summary) == 255  # HA truncates at 255
    assert len(asyncio.run(entity.async_release_notes())) == 400


def test_install_checks_first():
    """The install endpoint applies whatever the last check cached, so
    installing without checking installs a stale target or nothing at all."""
    version = {"version": "1.4.3", "state": "idle", "update_available": {"version": "1.4.4"}}
    coordinator = make_coordinator(version=version)
    entity = HtMarqueeUpdate(coordinator, FakeEntry())
    asyncio.run(entity.async_install(version=None, backup=False))
    assert coordinator.api.names == ["check_update", "install_update"]


def test_install_in_progress_while_the_device_is_working():
    version = {"version": "1.4.3", "state": "downloading", "update_available": {"version": "1.4.4"}}
    entity = HtMarqueeUpdate(make_coordinator(version=version), FakeEntry())
    assert entity.in_progress is True


def test_update_entity_hidden_on_firmware_without_the_endpoint():
    entity = HtMarqueeUpdate(make_coordinator(version={}), FakeEntry())
    assert entity.available is False


# ── Showtimes ───────────────────────────────────────────────────────────


def test_next_showtime_picks_the_earliest_future_time():
    """Whole days either side of now, so this can't flake near midnight."""
    from homeassistant.util import dt as dt_util

    today = dt_util.now().date()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()

    showtimes = [
        # Already past — must not win, and must not be counted.
        {"id": 1, "tmdb_id": 550, "movie_title": "Fight Club", "showtime_date": yesterday,
         "times": ["19:00"], "notes": None},
        # Later of the two future showings.
        {"id": 2, "tmdb_id": 603, "movie_title": "The Matrix", "showtime_date": tomorrow,
         "times": ["23:59"], "notes": None},
        {"id": 3, "tmdb_id": 27205, "movie_title": "Inception", "showtime_date": tomorrow,
         "times": ["00:01"], "notes": "lobby"},
    ]
    sensor = HtMarqueeNextShowtimeSensor(make_coordinator(showtimes=showtimes), FakeEntry())

    value = sensor.native_value
    assert value is not None
    assert value.strftime("%Y-%m-%d %H:%M") == f"{tomorrow} 00:01"
    assert value.tzinfo is not None  # HA rejects a naive timestamp sensor

    attrs = sensor.extra_state_attributes
    assert attrs["movie_title"] == "Inception"
    assert attrs["upcoming_count"] == 2  # yesterday's showing is excluded


def test_next_showtime_is_empty_when_nothing_is_scheduled():
    sensor = HtMarqueeNextShowtimeSensor(make_coordinator(), FakeEntry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"upcoming_count": 0}


def test_malformed_showtime_rows_do_not_crash_the_sensor():
    showtimes = [{"id": 1, "showtime_date": None, "times": ["nonsense", None]}]
    sensor = HtMarqueeNextShowtimeSensor(make_coordinator(showtimes=showtimes), FakeEntry())
    assert sensor.native_value is None
