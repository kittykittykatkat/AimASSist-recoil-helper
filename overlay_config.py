"""Validated persistent settings for the fullscreen status overlay."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


OVERLAY_FILE = Path(__file__).resolve().with_name("overlay.json")

_BADGE_DEFAULTS = {
    "recoil": {
        "enabled": True,
        "label": "RECOIL",
        "x": 40,
        "y": 40,
        "width": 150,
        "height": 42,
        "on_color": [0, 210, 120, 230],
        "off_color": [55, 55, 65, 180],
    },
    "burst": {
        "enabled": True,
        "label": "BURST",
        "x": 40,
        "y": 92,
        "width": 150,
        "height": 42,
        "on_color": [0, 170, 235, 230],
        "off_color": [55, 55, 65, 180],
    },
    "distance": {
        "enabled": True,
        "label": "DISTANCE",
        "x": 40,
        "y": 144,
        "width": 150,
        "height": 42,
        "on_color": [255, 170, 40, 230],
        "off_color": [0, 160, 95, 210],
    },
}

OVERLAY_DEFAULTS = {
    "mode": "Display Fuser",
    "background_color": [0, 0, 0, 255],
    "always_on_top": True,
    "click_through": True,
    "toggle_source": "Local keyboard / pedal",
    "toggle_key": "f8",
    "font_path": "",
    "font_scale": 1.0,
    "badges": _BADGE_DEFAULTS,
}


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def _color(value: Any, default: list[int]) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return default.copy()
    values = list(value[:4])
    if len(values) == 3:
        values.append(default[3])
    return [int(_number(channel, default[index], 0, 255)) for index, channel in enumerate(values)]


def validate_overlay_config(value: Any) -> dict:
    """Merge user settings with defaults and constrain renderer-facing values."""
    source = value if isinstance(value, dict) else {}
    result = copy.deepcopy(OVERLAY_DEFAULTS)
    mode = source.get("mode")
    if mode in ("Display Fuser", "Transparent"):
        result["mode"] = mode
    result["background_color"] = _color(
        source.get("background_color"), result["background_color"]
    )
    result["always_on_top"] = bool(source.get("always_on_top", True))
    result["click_through"] = bool(source.get("click_through", True))
    toggle_source = source.get("toggle_source")
    if toggle_source in ("Local keyboard / pedal", "KMBox Mouse 4", "KMBox Mouse 5"):
        result["toggle_source"] = toggle_source
    toggle_key = str(source.get("toggle_key", "f8")).strip().lower()
    result["toggle_key"] = toggle_key[:32] or "f8"
    result["font_path"] = str(source.get("font_path", "")).strip()[:1024]
    result["font_scale"] = _number(source.get("font_scale"), 1.0, 0.5, 3.0)

    badges = source.get("badges") if isinstance(source.get("badges"), dict) else {}
    for name, defaults in _BADGE_DEFAULTS.items():
        badge_source = badges.get(name) if isinstance(badges.get(name), dict) else {}
        badge = result["badges"][name]
        badge["enabled"] = bool(badge_source.get("enabled", defaults["enabled"]))
        label = str(badge_source.get("label", defaults["label"])).strip()
        badge["label"] = label[:24] or defaults["label"]
        badge["x"] = int(_number(badge_source.get("x"), defaults["x"], 0, 16384))
        badge["y"] = int(_number(badge_source.get("y"), defaults["y"], 0, 16384))
        badge["width"] = int(_number(badge_source.get("width"), defaults["width"], 30, 1000))
        badge["height"] = int(_number(badge_source.get("height"), defaults["height"], 16, 500))
        badge["on_color"] = _color(badge_source.get("on_color"), defaults["on_color"])
        badge["off_color"] = _color(badge_source.get("off_color"), defaults["off_color"])
    return result


def load_overlay_config(path: Path = OVERLAY_FILE) -> dict:
    """Load overlay settings, falling back safely when the file is absent or invalid."""
    try:
        with path.open(encoding="utf-8") as handle:
            return validate_overlay_config(json.load(handle))
    except (OSError, ValueError, TypeError):
        return validate_overlay_config({})


def save_overlay_config(config: dict, path: Path = OVERLAY_FILE) -> dict:
    """Validate and atomically save overlay settings."""
    validated = validate_overlay_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(validated, handle, indent=4)
        handle.write("\n")
    os.replace(temporary, path)
    return validated