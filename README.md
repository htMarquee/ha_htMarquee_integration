# htMarquee for Home Assistant

Home Assistant integration for [htMarquee](https://htmarquee.com), a smart movie poster display for home theater lobbies. It communicates with your htMarquee device over its local REST API.

## Features

> **Premiere tier required.** The Home Assistant integration and the REST API it uses are htMarquee Premiere features. The media player and sensors reflect whatever the device reports; everything that *controls* the device — Play Trailer, the TV (HDMI-CEC) entities, and every LED entity — is Premiere-gated and shows as unavailable on a Matinee (free) device. The TV and LED entities also need that hardware enabled on the device itself. See [Requirements](#requirements).

### Media Player
Control your htMarquee display as a standard Home Assistant media player:
- **Play/Pause** the poster slideshow
- **Skip** forward or back through movies
- **Select playlist** as the media source (or use Auto/Upcoming)
- **Search and browse** — search the movie catalogue from Home Assistant's media browser and send any title straight to the display. The browse root also lists your playlists, so a playlist is one tap from the same place.
- **Movie poster** shown as the media player thumbnail
- **External source awareness** — when an external app (e.g. Plex) is driving htMarquee, playback controls are automatically hidden and the app name is exposed via `app_name`
- **Rich attributes**: TMDB ID, genres, rating, runtime, vote average, RT score, Metacritic score, tagline, phase, current index, total items, state label

### Images
Poster art as first-class entities, so it can be used in any dashboard card:

- **`image.htmarquee_poster`** — the portrait theatrical poster for whatever is on screen
- **`image.htmarquee_backdrop`** — the wide 16:9 backdrop, which suits banner-style cards far better than a cropped poster
- **`image.htmarquee_studio_logo`** — the distributing studio's logo (transparent PNG)

These exist because the device's artwork cannot be linked to directly: every `/assets/*` path requires the API token, and the device presents a self-signed certificate, so a browser pointed at it draws a broken image. Home Assistant fetches the bytes with the API client's credentials and re-serves them from its own proxied URL.

Each entity reports unavailable when the current title has no such artwork — TMDB does not carry a backdrop or a studio logo for everything.

### LED strip
The full LED system, not just on/off:

- **`light.htmarquee_led_strip`** — power, brightness, RGB colour, and all **26 effects** in the effect list (Car Chase, Corner Flames, Poster Glow, Red Carpet, the Cross / Marquee / Spotlight families, and the rest). Attributes expose the current speed, palette, LED count and follow-display-state.
- **`select.htmarquee_led_palette`** — the active palette, including any custom palettes you've built on the device, plus **Color Picker** to hand colour control back to the light's RGB value.
- **`number.htmarquee_led_effect_speed`** — the 0-255 effect speed. The scale is exponential: the middle of the range is each effect's natural tempo, the top is roughly seven times faster, the bottom roughly an eighth. Halving the number does not halve the speed.
- **`scene.htmarquee_led_*`** — one scene per **LED preset** saved on the device. Activating it applies that saved look. Presets you create later appear automatically.
- **`switch.htmarquee_led_follow_display_state`** — whether the slideshow drives the LEDs (ambient while idle, dimmed during playback) or they hold whatever you set.

Two things worth knowing, because they are device behaviour rather than integration quirks:

- Setting an **RGB colour** while an effect is running also switches the palette to *Color Picker*. In palette mode the strip ignores the picked colour entirely, so without that the colour change would silently do nothing.
- **Any** manual change — from here, the web UI, or anywhere else — turns *follow display state* off on the device. That is deliberate: manual control wins.

### TV (HDMI-CEC)
- **`switch.htmarquee_tv`** — TV power **with state**, so `if the TV is on` finally works in automations. Reports *unknown* rather than guessing when the CEC adapter can't tell. This is the one to use.
- **`button.htmarquee_tv_on` / `button.htmarquee_tv_off`** — the older one-shot CEC commands, kept so existing automations keep working. Still handy on a dashboard: a toggle already showing "on" can't be tapped to re-assert "on" at a TV that ignored the first command.

CEC power reporting lags a few seconds behind a command — the device fires it in the background and reads the TV back afterwards.

### Updates
- **`update.htmarquee`** — surfaces htMarquee's own OTA updates in Home Assistant's update dashboard, with the release notes and an Install button. The device never auto-installs; this is a second front door to the same deliberate human decision as Settings → Maintenance in its web UI.

### Sensors
- **Current Movie** — title with metadata attributes (year, genres, rating, vote average, runtime, RT score, Metacritic score, tagline, aspect ratio, poster URL, state label)
- **Slideshow Phase** — current phase (POSTER_REVEAL, TRAILER, POSTER_HOLD, TRANSITION, INTERSTITIAL) with phase duration, transition effect, and paused state
- **Next Showtime** — the next Scheduled Showing as a timestamp, with the movie title and the day's other times as attributes. Premiere-only; the entity isn't created if the device doesn't offer the feature. Times are read in Home Assistant's timezone, which is right whenever both live in the same house. The `upcoming` attribute carries the whole schedule ahead as a list — one entry per screening, so a film with two showings that day appears twice — capped at 10 so the attribute cannot grow without bound.
- **Diagnostics**: CPU Usage, Memory Usage, CPU Temperature, Last Boot, Cache Disk Free

### Buttons
- **Play Trailer** — trigger the current movie's trailer on the display

### Services
- **`htmarquee.spotlight`** — search for a movie by title and spotlight the top result on the display. Takes an optional `device_id` if you have more than one marquee.
- **`htmarquee.led_effect`** — set effect, speed and palette in a single call. Each of those restarts the running effect on the device, so doing it in one call means one visible cut instead of three.

### Diagnostics
Download diagnostics from the device page to capture exactly what the marquee reported — status, hardware state, metrics, playlists, presets and palettes — with credentials redacted.

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Click the three dots menu and select **Custom repositories**
3. Add `https://github.com/htMarquee/ha_htMarquee_integration` with category **Integration**
4. Search for "htMarquee" and install
5. Restart Home Assistant

### Manual
1. Copy the `custom_components/htmarquee` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **htMarquee**
3. Enter your device's hostname or full URL (e.g. `htmarquee.local`, `https://10.0.1.50:8443`) and port (default: `443`)
4. If authentication is enabled, enter your credentials on the next step

The integration auto-detects whether your htMarquee instance requires authentication and supports both password and PIN auth modes. If you later change the device's password or PIN, Home Assistant prompts you to re-enter it rather than silently retrying a dead credential.

## Automation Examples

### Spotlight a movie when a scene is activated
```yaml
automation:
  - alias: "Movie Night - Interstellar"
    trigger:
      - platform: state
        entity_id: scene.movie_night
    action:
      - service: htmarquee.spotlight
        data:
          query: "Interstellar"
```

### Premiere-night lighting when the TV comes on
```yaml
automation:
  - alias: "Marquee lights up with the TV"
    trigger:
      - platform: state
        entity_id: switch.htmarquee_tv
        to: "on"
    action:
      - service: htmarquee.led_effect
        target:
          entity_id: light.htmarquee_led_strip
        data:
          effect: "Spotlight - Premiere Night"
          speed: 170
          palette: "cinema"
```

### Apply a saved LED preset
```yaml
automation:
  - alias: "Lobby lights for movie night"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: scene.turn_on
        target:
          entity_id: scene.htmarquee_led_movie_night
```

### Warn before a scheduled showing
```yaml
automation:
  - alias: "Fifteen minutes to showtime"
    trigger:
      - platform: template
        value_template: >-
          {{ states('sensor.htmarquee_next_showtime') | as_datetime - now()
             < timedelta(minutes=15) }}
    action:
      - service: button.press
        target:
          entity_id: button.htmarquee_tv_on
```

### Set LED strip colour to match the season
```yaml
automation:
  - alias: "Holiday LED colors"
    trigger:
      - platform: time
        at: "17:00:00"
    condition:
      - condition: template
        value_template: "{{ now().month == 12 }}"
    action:
      - service: light.turn_on
        target:
          entity_id: light.htmarquee_led_strip
        data:
          rgb_color: [255, 0, 0]
          brightness: 200
```

## Requirements

- Home Assistant 2024.6.0 or newer
- An htMarquee device reachable on your local network. It defaults to `htmarquee.local`, but the mDNS hostname is user-configurable on the device (e.g. `htmarquee-livingroom.local`), so enter whatever name/IP your device uses.
- **htMarquee Premiere tier** — the Home Assistant integration and REST API are Premiere features. The media-player and sensor entities reflect whatever the device reports; the Play Trailer button, TV (HDMI-CEC) entities, and every LED entity require Premiere (and the TV/LED entities also require CEC/LED hardware enabled on the device).

## Development

### Tests

`tests/test_entities.py` drives the real entity code against the payload shapes the device actually returns, faking only the HTTP client. It needs `homeassistant` importable but no running Home Assistant:

```bash
pip install homeassistant pytest
python -m pytest tests/ -q
```

### Effect-list drift

The LED effect list in `const.py` is a hand-maintained copy of the device's own — the API has no endpoint that enumerates effects. After any LED effect change in the app, check the two haven't drifted apart:

```bash
python tools/check_effect_parity.py [path/to/htmarquee]
```
