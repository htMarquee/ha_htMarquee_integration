# htMarquee Home Assistant Integration — CLAUDE.md

HACS custom integration (domain `htmarquee`) that controls an htMarquee device over its local **REST API**. Part of the htMarquee workspace — see [`../CLAUDE.md`](../CLAUDE.md).

## Source of truth

The **app** (`../htmarquee/`) is the source of truth: the REST API this integration calls, the entities/services it can expose, and the tier gating all live there. When the app's API or tier behavior changes, update this README and `manifest.json` in the **same** pass. Validate against the app code, not a summary.

## Project specifics

- **Premiere tier:** the HA integration and the REST API it relies on are Premiere features. The Play Trailer button, TV (HDMI-CEC) buttons, and LED Strip light are Premiere-gated (and the TV/LED entities also require that hardware enabled on the device). The README must say so.
- **What the code actually provides:** platforms `media_player`, `sensor`, `button`, `light`, plus the `htmarquee.spotlight` service. Keep the README's feature list matched to the registered entities/services — don't claim entities the code doesn't create (`switch.py` is an unused stub).
- **Config flow:** host (default `htmarquee.local`, but the device's mDNS name is user-configurable, e.g. `htmarquee-livingroom.local`), port (default `443`), SSL on, optional password/PIN auth.
- **Repo URLs:** the canonical repo is `github.com/htMarquee/ha_htMarquee_integration` — `manifest.json`'s `documentation` and `issue_tracker` must point here, with the correct `htMarquee` casing.
- **Versioning:** `manifest.json` `version` tracks the integration independently of the app version.
