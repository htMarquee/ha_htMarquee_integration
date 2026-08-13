#!/usr/bin/env python3
"""Verify the integration's LED effect list still matches the app.

The device is the source of truth for effects, but it has no endpoint that
enumerates them — so ``const.LED_EFFECTS`` is a hand-maintained copy living
in a different repository from the thing it copies. That is exactly the kind
of duplication that rots silently: an effect renamed in the app keeps
working in the web UI and quietly disappears from Home Assistant.

This diffs the copy against both halves of the original:

* ``EFFECT_MAP`` in ``backend/features/hardware/led_service.py`` — the set of
  effect names the API accepts.
* the ``#hw-led-effect`` dropdown in ``frontend/index.html`` — the labels the
  device shows users, which the integration mirrors so the two UIs agree.

Run it after any LED effect change:

    python tools/check_effect_parity.py [path/to/htmarquee]

Exits non-zero and prints the differences when they have drifted apart.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Both projects live side by side under the htMarquee workspace root.
DEFAULT_APP_ROOT = REPO_ROOT.parent / "htmarquee"


def load_integration_effects() -> dict[str, str]:
    """Read LED_EFFECTS without importing homeassistant."""
    source = (REPO_ROOT / "custom_components" / "htmarquee" / "const.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"LED_EFFECTS: dict\[str, str\] = \{(.*?)\n\}", source, re.S)
    if not match:
        raise SystemExit("Could not find LED_EFFECTS in const.py")
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', match.group(1)))


def load_app_effect_names(app_root: Path) -> set[str]:
    """Effect names the device API accepts (EFFECT_MAP values)."""
    path = app_root / "backend" / "features" / "hardware" / "led_service.py"
    source = path.read_text(encoding="utf-8")
    match = re.search(r"^EFFECT_MAP = \{(.*?)\n\}", source, re.S | re.M)
    if not match:
        raise SystemExit(f"Could not find EFFECT_MAP in {path}")
    return set(re.findall(r'\d+:\s*"([^"]+)"', match.group(1)))


def load_app_effect_labels(app_root: Path) -> dict[str, str]:
    """Effect labels from the device's own dropdown, normalised.

    The dropdown labels carry a colour-mode tag the integration drops —
    "Cross &mdash; Six Arms (perimeter &middot; color or palette)" is
    "Cross - Six Arms" in Home Assistant, where an em dash is a nuisance to
    type into a YAML automation.
    """
    path = app_root / "frontend" / "index.html"
    source = path.read_text(encoding="utf-8")
    match = re.search(r'<select id="hw-led-effect".*?</select>', source, re.S)
    if not match:
        raise SystemExit(f"Could not find the #hw-led-effect dropdown in {path}")

    labels: dict[str, str] = {}
    for name, raw in re.findall(r'<option value="([^"]+)">([^<]+)</option>', match.group(0)):
        text = html.unescape(raw)
        text = re.sub(r"\s*\([^)]*\)\s*$", "", text)  # drop "(perimeter · palette)"
        labels[name] = text.replace("—", "-").replace("–", "-").strip()
    return labels


def main() -> int:
    app_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_APP_ROOT
    if not app_root.is_dir():
        raise SystemExit(f"htMarquee app not found at {app_root} — pass its path as an argument")

    ours = load_integration_effects()
    api_names = load_app_effect_names(app_root)
    app_labels = load_app_effect_labels(app_root)

    problems: list[str] = []

    for name in sorted(set(ours) - api_names):
        problems.append(f"  - '{name}' is offered by the integration but the API rejects it")
    for name in sorted(api_names - set(ours)):
        problems.append(f"  - '{name}' exists on the device but the integration never offers it")

    # The dropdown is the user-facing half; an effect missing from it is a
    # device-side omission, not something this integration can fix.
    for name in sorted(set(ours) & set(app_labels)):
        if ours[name] != app_labels[name]:
            problems.append(
                f"  - '{name}' label drifted: integration {ours[name]!r} vs device "
                f"{app_labels[name]!r}"
            )

    if problems:
        print(f"LED effect parity FAILED ({len(problems)} difference(s)):")
        print("\n".join(problems))
        return 1

    print(f"LED effect parity OK — {len(ours)} effects match {app_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
