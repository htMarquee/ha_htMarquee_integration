# htMarquee Home Assistant Integration — CLAUDE.md

HACS custom integration (domain `htmarquee`) that controls an htMarquee device over its local **REST API**. Part of the htMarquee workspace — see [`../CLAUDE.md`](../CLAUDE.md).

## Source of truth

The **app** (`../htmarquee/`) is the source of truth: the REST API this integration calls, the entities/services it can expose, and the tier gating all live there. When the app's API or tier behavior changes, update this README and `manifest.json` in the **same** pass. Validate against the app code, not a summary.

## Project specifics

- **Premiere tier:** the HA integration and the REST API it relies on are Premiere features. Everything that *controls* the device — Play Trailer, the TV (HDMI-CEC) entities, and every LED entity — is Premiere-gated (and the TV/LED entities also require that hardware enabled on the device). The README must say so.
- **What the code actually provides:** platforms `button`, `light`, `media_player`, `number`, `scene`, `select`, `sensor`, `switch`, `update`, plus `diagnostics.py` and the `htmarquee.spotlight` / `htmarquee.led_effect` services. Keep the README's feature list matched to the registered entities/services — don't claim entities the code doesn't create.
- **Entities share one base** (`entity.py`): `HtMarqueeEntity` owns the `DeviceInfo` and the unique-id scheme, `HtMarqueeLedEntity` adds the Premiere + LED-hardware availability gate. Never hand-roll `device_info` in a platform again — that is how `sw_version` came to appear on only one entity.
- **Unique-id keys are load-bearing.** They are `{entry_id}_{key}`; changing a key orphans a user's entity and its history. Existing keys: `media_player`, `phase`, `movie`, `play_trailer`, `tv_on`, `tv_off`, `led`.
- **Effect list drift:** the device has no endpoint that enumerates LED effects, so `const.LED_EFFECTS` is a hand-maintained copy of the app's `EFFECT_MAP` + its `#hw-led-effect` dropdown labels. After any LED effect change in the app, run `python tools/check_effect_parity.py` — it fails on drift.
- **Anything that writes to the strip or the TV** must finish with `coordinator.async_refresh_hardware()`, not `async_request_refresh()`: the latter only re-polls `/api/status`, so the change sits stale in HA until the 30s hardware deadline.
- **Config flow:** host (default `htmarquee.local`, but the device's mDNS name is user-configurable, e.g. `htmarquee-livingroom.local`), port (default `443`), SSL on, optional password/PIN auth, plus a reauth step for when the device's password/PIN changes.
- **Minimum HA version** is whatever the code actually uses, and `hacs.json` must say so. `entry.runtime_data` alone puts the floor at 2024.6.0.
- **Repo URLs:** the canonical repo is `github.com/htMarquee/ha_htMarquee_integration` — `manifest.json`'s `documentation` and `issue_tracker` must point here, with the correct `htMarquee` casing.
- **Brand icon lives in `custom_components/htmarquee/brand/`** (`icon.png` 256×256, `icon@2x.png` 512×512, square PNG). Since HA **2026.3** custom integrations ship their own brand images there and HA serves them from `/api/brands/integration/htmarquee/icon.png`; the `home-assistant/brands` repo auto-closes PRs for custom integrations, so don't send one. Anything older than 2026.3 shows "icon not available" and there is no fix for it. Note HACS's own downloads panel still queries the public CDN, so it keeps showing the placeholder even when the Integrations page is correct — that's [hacs/integration#5223](https://github.com/hacs/integration/issues/5223), not a fault here.
- **Versioning:** `manifest.json` `version` tracks the integration independently of the app version.
