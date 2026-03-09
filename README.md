# htMarquee for Home Assistant

Home Assistant integration for [htMarquee](https://htmarquee.com), a smart movie poster display system for home theater lobbies.

## Features

### Media Player
Control your htMarquee display as a standard Home Assistant media player:
- **Play/Pause** the poster slideshow
- **Skip** forward or back through movies
- **Select playlist** as the media source (or use Auto/Upcoming)
- **Movie poster** shown as the media player thumbnail
- **Rich attributes**: TMDB ID, genres, rating, runtime, RT score, Metacritic score, tagline, phase info

### Sensors
- **Current Movie** — title with metadata attributes (year, genres, ratings, poster URL, aspect ratio)
- **Slideshow Phase** — current phase (POSTER_REVEAL, TRAILER, POSTER_HOLD, TRANSITION, INTERSTITIAL) with duration and transition effect

### Buttons
- **Play Trailer** — trigger the current movie's trailer on the display
- **TV On / TV Off** — HDMI-CEC power control (available when CEC is enabled on the device)

### Light
- **LED Strip** — control the htMarquee LED strip with on/off, brightness, and RGB color (available when LED hardware is enabled)

### Services
- **`htmarquee.spotlight`** — search for a movie by title and spotlight the top result on the display

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Click the three dots menu and select **Custom repositories**
3. Add `https://github.com/htMarquee/homeassistant` with category **Integration**
4. Search for "htMarquee" and install
5. Restart Home Assistant

### Manual
1. Copy the `custom_components/htmarquee` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **htMarquee**
3. Enter your device's hostname (default: `htmarquee.local`) and port (default: `443`)
4. If authentication is enabled, enter your credentials on the next step

The integration auto-detects whether your htMarquee instance requires authentication and supports both password and PIN auth modes.

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

### Turn on the display TV before movie night
```yaml
automation:
  - alias: "Turn on theater display"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.htmarquee_tv_on
```

### Set LED strip color to match the season
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

- Home Assistant 2024.1.0 or newer
- htMarquee device accessible on your local network
