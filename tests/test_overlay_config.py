import json

from overlay_config import load_overlay_config, save_overlay_config, validate_overlay_config
from overlay_renderer import (
    _background_opacity,
    _badge_at,
    _badge_color,
    _clamp_badge_position,
    _colorref,
)


def test_overlay_defaults_are_black_and_have_three_badges():
    config = validate_overlay_config({})

    assert config["mode"] == "Display Fuser"
    assert config["background_color"] == [0, 0, 0, 255]
    assert config["toggle_key"] == "f8"
    assert config["toggle_source"] == "Local keyboard / pedal"
    assert config["font_path"] == ""
    assert set(config["badges"]) == {"recoil", "burst", "distance"}


def test_overlay_config_clamps_renderer_values():
    config = validate_overlay_config({
        "mode": "invalid",
        "font_scale": 100,
        "background_color": [-1, 300, "bad", 80],
        "badges": {
            "recoil": {
                "label": "x" * 100,
                "x": -50,
                "width": 2,
                "height": 9000,
            }
        },
    })

    assert config["mode"] == "Display Fuser"
    assert config["font_scale"] == 3.0
    assert config["background_color"] == [0, 255, 0, 80]
    assert len(config["badges"]["recoil"]["label"]) == 24
    assert config["badges"]["recoil"]["x"] == 0
    assert config["badges"]["recoil"]["width"] == 30
    assert config["badges"]["recoil"]["height"] == 500


def test_overlay_config_round_trip_is_atomic(tmp_path):
    path = tmp_path / "overlay.json"
    saved = save_overlay_config({
        "mode": "Transparent",
        "toggle_key": "F10",
        "toggle_source": "KMBox Mouse 4",
        "font_path": "C:/Windows/Fonts/arial.ttf",
        "badges": {"distance": {"enabled": False, "x": 321}},
    }, path)

    assert load_overlay_config(path) == saved
    assert saved["toggle_key"] == "f10"
    assert saved["toggle_source"] == "KMBox Mouse 4"
    assert saved["font_path"] == "C:/Windows/Fonts/arial.ttf"
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "Transparent"


def test_renderer_uses_module_and_distance_states():
    config = validate_overlay_config({})
    recoil = config["badges"]["recoil"]
    distance = config["badges"]["distance"]

    assert _badge_color("recoil", recoil, {"recoil_enabled": True}) == recoil["on_color"]
    assert _badge_color("recoil", recoil, {"recoil_enabled": False}) == recoil["off_color"]
    assert _badge_color("distance", distance, {"distance_2x": True}) == distance["on_color"]
    assert _badge_color("distance", distance, {"distance_2x": False}) == distance["off_color"]


def test_colorref_uses_windows_bgr_integer_layout():
    assert _colorref([1, 2, 3, 255]) == 0x030201


def test_fullscreen_drag_hit_tests_visible_badges():
    config = validate_overlay_config({})

    assert _badge_at(config, 50, 50) == "recoil"
    assert _badge_at(config, 50, 100) == "burst"
    assert _badge_at(config, 500, 500) is None

    config["badges"]["recoil"]["enabled"] = False
    assert _badge_at(config, 50, 50) is None


def test_fullscreen_drag_clamps_badges_to_screen():
    badge = {"width": 150, "height": 42}

    assert _clamp_badge_position(badge, -10, -20, 1920, 1080) == (0, 0)
    assert _clamp_badge_position(badge, 1900, 1070, 1920, 1080) == (1770, 1038)


def test_background_opacity_uses_saved_alpha_channel():
    config = validate_overlay_config({"background_color": [10, 20, 30, 0]})
    assert _background_opacity(config) == 0.0

    config["background_color"][3] = 128
    assert _background_opacity(config) == 128 / 255.0

    config["background_color"][3] = 255
    assert _background_opacity(config) == 1.0