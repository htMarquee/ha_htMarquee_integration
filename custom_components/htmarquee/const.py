"""Constants for the htMarquee integration."""

DOMAIN = "htmarquee"
MANUFACTURER = "htMarquee"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USE_SSL = "use_ssl"
CONF_TOKEN = "token"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

DEFAULT_PORT = 443
TIER_PREMIERE = "premiere"
TIER_MATINEE = "matinee"
DEFAULT_SCAN_INTERVAL = 10  # seconds
PLAYLIST_SCAN_INTERVAL = 60  # seconds
HARDWARE_SCAN_INTERVAL = 30  # seconds

# State mapping: htMarquee state -> HA MediaPlayerState value
STATE_MAP = {
    "IDLE": "idle",
    "ACTIVE": "playing",
    "MANUAL": "paused",
    "OFFLINE": "off",
}

PLATFORMS = ["media_player", "sensor", "button", "light"]
