"""Constants for the htMarquee integration."""

from homeassistant.const import Platform

DOMAIN = "htmarquee"
MANUFACTURER = "htMarquee"
MODEL = "Smart Movie Poster Display"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USE_SSL = "use_ssl"
CONF_TOKEN = "token"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

DEFAULT_PORT = 443
TIER_PREMIERE = "premiere"
TIER_MATINEE = "matinee"

# Poll cadence. /api/status is cheap and drives the media player, so it sets
# the coordinator interval; everything else rides slower deadlines measured
# from the same tick (see coordinator._async_update_data).
DEFAULT_SCAN_INTERVAL = 10  # seconds — /api/status
HARDWARE_SCAN_INTERVAL = 30  # seconds — LED/CEC state, metrics, version
PLAYLIST_SCAN_INTERVAL = 60  # seconds — playlists, LED presets
CATALOG_SCAN_INTERVAL = 300  # seconds — palettes, scheduled showtimes

# CEC power is a round trip through the TV: the device fires the command in
# the background and its own monitor switches to fast polling, so the new
# state shows up a few seconds later. Re-read hardware once after that
# settles rather than making the user wait for the next 30s tick.
CEC_SETTLE_SECONDS = 6

# State mapping: htMarquee state -> HA MediaPlayerState value.
# The device dropped its OFFLINE state in the LED release; unknown values
# still fall back to "off" in media_player rather than raising.
STATE_MAP = {
    "IDLE": "idle",
    "ACTIVE": "playing",
    "MANUAL": "paused",
}

SOURCE_AUTO = "Auto (Upcoming)"

PLATFORMS = [
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SCENE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

# The device treats this pseudo-palette as "ignore the palette, use the
# colour picker". It is not returned by /api/led/palettes, so it has to be
# prepended by hand — same as the device's own web UI does.
PALETTE_COLOR_PICKER = "color_picker"
PALETTE_COLOR_PICKER_LABEL = "Color Picker"

# Device effect name -> the label shown in Home Assistant. Mirrors the
# device's own effect dropdown (frontend/index.html) minus the "(perimeter ·
# palette)" colour-mode tags, with ASCII hyphens so the labels are painless
# to type in YAML automations.
#
# This list is duplicated across two repos, so it drifts silently unless
# something checks: tools/check_effect_parity.py diffs it against the app's
# EFFECT_MAP and dropdown labels. Run it after any LED effect change.
LED_EFFECTS: dict[str, str] = {
    "breathing": "Breathing",
    "car_chase": "Car Chase",
    "chase_rainbow": "Chase Rainbow",
    "colorloop": "Color Loop",
    "corner_fire": "Corner Flames",
    "cross": "Cross",
    "cross_continuous": "Cross - Continuous",
    "cross_six": "Cross - Six Arms",
    "electron": "Electron",
    "gradient": "Gradient",
    "marquee": "Marquee - Alternating",
    "grand_marquee": "Marquee - Grand Chase",
    "theater_comet": "Marquee - Tail",
    "theater_chase": "Marquee - Tight",
    "now_showing": "Now Showing Pulse",
    "paparazzi": "Paparazzi",
    "poster_glow": "Poster Glow",
    "rainbow": "Rainbow",
    "red_carpet": "Red Carpet",
    "aurora": "Silver Screen",
    "solid": "Solid",
    "spotlights": "Spotlight",
    "dual_spotlights": "Spotlight - Dual",
    "premiere_night": "Spotlight - Premiere Night",
    "quad_spotlights": "Spotlight - Quad",
    "wipe": "Wipe",
}

LED_EFFECT_LABELS = sorted(LED_EFFECTS.values())
LABEL_TO_LED_EFFECT = {label: name for name, label in LED_EFFECTS.items()}

SERVICE_SPOTLIGHT = "spotlight"
SERVICE_LED_EFFECT = "led_effect"
ATTR_QUERY = "query"
ATTR_SPEED = "speed"
ATTR_PALETTE = "palette"


def palette_label(name: str) -> str:
    """Device palette name -> the label shown in Home Assistant.

    Mirrors the device's own palette dropdown: underscores become spaces and
    each word is capitalised, so ``warm_white`` reads as "Warm White". Custom
    palettes are user-named and may already contain spaces or capitals, which
    this leaves intact.
    """
    if name == PALETTE_COLOR_PICKER:
        return PALETTE_COLOR_PICKER_LABEL
    return name.replace("_", " ").title()


def palette_from_label(label: str, known: list[str]) -> str:
    """Label -> device palette name, tolerating a raw name being passed in.

    Automations may reasonably send either the pretty label the UI shows or
    the raw name the API documents, so accept both. Anything unrecognised is
    passed through untouched and the device decides — a custom palette named
    "Bond Villain" must survive this round trip verbatim.
    """
    if label == PALETTE_COLOR_PICKER_LABEL:
        return PALETTE_COLOR_PICKER
    for name in known:
        if label in (name, palette_label(name)):
            return name
    return label
