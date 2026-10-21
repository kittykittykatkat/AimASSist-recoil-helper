import queue
import sys
import threading
import time
import types

# The VM baseline does not include the GUI/input packages. Lifecycle tests only
# need their import surfaces; hardware and UI behavior remain out of scope.
keyboard_stub = types.ModuleType("keyboard")
keyboard_stub.is_pressed = lambda key: False
dearpygui_package = types.ModuleType("dearpygui")
dearpygui_stub = types.ModuleType("dearpygui.dearpygui")
dearpygui_package.dearpygui = dearpygui_stub
sys.modules.setdefault("keyboard", keyboard_stub)
sys.modules.setdefault("dearpygui", dearpygui_package)
sys.modules.setdefault("dearpygui.dearpygui", dearpygui_stub)

import master_control
import pytest


def test_linear_mod_links_stay_synchronized(monkeypatch):
    values = {}
    monkeypatch.setattr(master_control.dpg, "set_value", values.__setitem__, raising=False)
    monkeypatch.setattr(master_control, "PENDING_SETTINGS", {})
    master_control.callback_linear_enabled(None, True)
    assert values["ui_linear_enabled"] is True
    assert values["ui_toggle_linear_mod"] is True
    assert values["ui_toggle_recoil_mod"] is False
    master_control.callback_linear_enabled(None, False)
    assert values["ui_linear_enabled"] is False
    assert values["ui_toggle_linear_mod"] is False


@pytest.fixture(autouse=True)
def isolate_device_recovery(monkeypatch):
    monkeypatch.setattr(master_control, "DEVICE_RECOVERY_BLOCKED", threading.Event())
    monkeypatch.setattr(master_control, "_device_retry_config", None)
    monkeypatch.setattr(master_control, "DEFAULT_STATE", master_control.DEFAULT_STATE.copy())


def test_fault_requires_recovery_then_explicit_hotkey(monkeypatch):
    master_control.DEFAULT_STATE["master_active"] = True
    master_control.pause_for_device_fault()
    assert not master_control.DEFAULT_STATE["master_active"]
    assert not master_control.toggle_master_output()
    master_control.DEVICE_RECOVERY_BLOCKED.clear()
    assert not master_control.DEFAULT_STATE["master_active"]
    assert master_control.toggle_master_output()


def test_reconnect_is_bounded_and_does_not_rearm(monkeypatch):
    device = master_control.KMBoxDevice()
    monkeypatch.setattr(master_control, "DEVICE", device)
    monkeypatch.setattr(master_control, "DEVICE_REQUESTS", queue.Queue(maxsize=1))
    monkeypatch.setattr(master_control, "DEVICE_HEALTH", {"attempts": 0})
    monkeypatch.setattr(master_control, "_device_retry_config", {"device_type": "KMBox"})
    monkeypatch.setattr(master_control, "_device_retry_at", 0)
    calls = []
    monkeypatch.setattr(master_control, "connect_device_from_config", lambda cfg: calls.append(cfg) or False)
    for now in range(0, 100, 10):
        monkeypatch.setattr(master_control.time, "monotonic", lambda: now)
        master_control.service_device_connection(now)
    assert len(calls) == 5
    assert master_control.DEVICE_RECOVERY_BLOCKED.is_set()
    assert not master_control.DEFAULT_STATE["master_active"]


def test_repeated_fault_pause_does_not_flood_ui():
    drain_ui_updates()
    master_control.pause_for_device_fault()
    master_control.pause_for_device_fault()
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == ("status", False)
    assert master_control.UI_UPDATE_QUEUE.empty()


def test_retry_delay_starts_after_initialization_finishes(monkeypatch):
    monkeypatch.setattr(master_control, "DEVICE", master_control.KMBoxDevice())
    monkeypatch.setattr(master_control, "DEVICE_REQUESTS", queue.Queue(maxsize=1))
    monkeypatch.setattr(master_control, "DEVICE_HEALTH", {"attempts": 0})
    monkeypatch.setattr(master_control, "_device_retry_config", {"device_type": "KMBox"})
    monkeypatch.setattr(master_control, "_device_retry_at", 0)
    monkeypatch.setattr(master_control.time, "monotonic", lambda: 15.0)
    monkeypatch.setattr(master_control, "connect_device_from_config", lambda cfg: False)
    master_control.service_device_connection(10.0)
    assert master_control._device_retry_at == 16.0


def test_import_preserves_shak_interval_and_legacy_fallback(tmp_path, monkeypatch):
    values = {"ui_time_interval": 0.15}
    monkeypatch.setattr(master_control.dpg, "get_value", values.get, raising=False)
    monkeypatch.setattr(master_control.dpg, "set_value", values.__setitem__, raising=False)
    monkeypatch.setattr(master_control, "redraw_recoil_canvas", lambda: None)
    monkeypatch.setattr(master_control, "_update_node_info", lambda: None)
    monkeypatch.setattr(master_control, "DEFAULT_STATE", {})
    monkeypatch.setattr(master_control, "PENDING_SETTINGS", {})
    path = tmp_path / "shak.txt"
    path.write_text("# interval_ms=250\n0, 0\n1, 2\n")
    master_control.callback_import_file_ok(None, {"selections": {"shak": str(path)}})
    assert values["ui_time_interval"] == 0.25
    assert master_control.DEFAULT_STATE["recoil_nodes"][1] == [0.25, 1, 2]
    path.write_text("0, 0\n3, 4\n")
    values["ui_time_interval"] = 0.1
    master_control.callback_import_file_ok(None, {"selections": {"shak": str(path)}})
    assert master_control.DEFAULT_STATE["recoil_nodes"][1] == [0.1, 3, 4]


def test_legacy_profile_uses_complete_defaults():
    profile = master_control.normalize_profile({"recoil_scale_x": 1.25})
    assert profile["recoil_scale_x"] == 1.25
    assert profile["local_sens"] == 22.0
    assert profile["local_zoom_mult"] == 0.75
    assert profile["far_scale_x"] == 2.0
    assert "master_active" not in profile


def test_profile_rejects_invalid_nodes_and_zero_divisors():
    import pytest
    for value in ({"recoil_nodes": [[0, 1]]}, {"local_sens": 0},
                  {"burst_intra_delay_ms": 0}):
        with pytest.raises(ValueError):
            master_control.normalize_profile(value)
    assert master_control.normalize_profile({"recoil_nodes": []})["recoil_nodes"] == [[0, 0, 0]]


def test_settings_coalesce_final_slider_value(monkeypatch):
    monkeypatch.setattr(master_control, "PENDING_SETTINGS", {})
    for value in range(100):
        master_control.queue_runtime_settings({"recoil_scale_x": value})
    master_control.queue_runtime_settings({"recoil_scale_y": 1.5})
    assert master_control.PENDING_SETTINGS == {"recoil_scale_x": 99, "recoil_scale_y": 1.5}


def test_empty_canvas_layout_is_safe(monkeypatch):
    monkeypatch.setattr(master_control, "DEFAULT_STATE", {"recoil_nodes": []})
    points, scale, origin = master_control._compute_canvas_layout()
    assert points == []
    assert scale == 1.0


class RecordingDevice(master_control.HWDevice):
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True

    def is_down(self, button):
        return False


def drain_ui_updates():
    while True:
        try:
            master_control.UI_UPDATE_QUEUE.get_nowait()
        except queue.Empty:
            return


def test_keyboard_listener_stops_when_requested(monkeypatch):
    stop_event = threading.Event()
    monkeypatch.setattr(master_control.keyboard, "is_pressed", lambda key: False)
    worker = threading.Thread(
        target=master_control.main_pc_keyboard_listener_worker,
        args=(stop_event,),
    )

    worker.start()
    stop_event.set()
    worker.join(timeout=0.5)

    assert not worker.is_alive()


def test_hardware_engine_stops_when_requested(monkeypatch):
    stop_event = threading.Event()
    device = RecordingDevice()
    monkeypatch.setattr(master_control, "DEVICE", device)
    worker = threading.Thread(
        target=master_control.hardware_consumer_engine,
        args=(queue.Queue(), stop_event),
    )

    worker.start()
    time.sleep(0.01)
    stop_event.set()
    worker.join(timeout=0.5)

    assert not worker.is_alive()


def test_shutdown_signals_joins_and_disconnects(monkeypatch):
    stop_event = threading.Event()
    device = RecordingDevice()
    monkeypatch.setattr(master_control, "DEVICE", device)
    worker = threading.Thread(target=stop_event.wait, name="test-worker")
    worker.start()

    master_control.shutdown_runtime(stop_event, [worker])

    assert stop_event.is_set()
    assert not worker.is_alive()
    assert device.disconnected


def test_recoil_runs_while_settings_tab_is_visible():
    state = master_control.DEFAULT_STATE.copy()
    state.update(active_tab="Settings", recoil_module_enabled=True)

    mode, is_firing = master_control.select_runtime_mode(
        state, recoil_triggered=True, burst_triggered=False, ads=True
    )

    assert (mode, is_firing) == ("Recoil", True)


def test_burst_runs_while_settings_tab_is_visible():
    state = master_control.DEFAULT_STATE.copy()
    state.update(active_tab="Settings", burst_module_enabled=True)

    mode, is_firing = master_control.select_runtime_mode(
        state, recoil_triggered=False, burst_triggered=True, ads=True
    )

    assert (mode, is_firing) == ("Burst", True)


def test_recoil_has_priority_when_both_modules_trigger():
    state = master_control.DEFAULT_STATE.copy()
    state.update(recoil_module_enabled=True, burst_module_enabled=True)

    mode, is_firing = master_control.select_runtime_mode(
        state, recoil_triggered=True, burst_triggered=True, ads=True
    )

    assert (mode, is_firing) == ("Recoil", True)


def test_far_scale_uses_independent_axes_only_in_far_mode():
    assert master_control.get_far_scale_multipliers(False, 1.1, 1.45) == (1.0, 1.0)
    assert master_control.get_far_scale_multipliers(True, 1.1, 1.45) == (1.1, 1.45)


def test_far_scale_snaps_and_clamps():
    assert master_control.snap_far_scale(0.1) == 0.5
    assert master_control.snap_far_scale(1.43) == 1.45
    assert master_control.snap_far_scale(3.0) == 2.5


def test_overlay_opacity_snaps_to_five_percent_steps():
    assert master_control.snap_overlay_opacity(0.0) == 0.0
    assert master_control.snap_overlay_opacity(0.63) == 0.65
    assert master_control.snap_overlay_opacity(0.98) == 1.0
    assert master_control.snap_overlay_opacity(-1) == 0.0


def test_distance_scale_latch_toggles_once_per_press():
    active, previous = master_control.update_distance_scale_latch(False, True, False)
    assert (active, previous) == (True, True)

    active, previous = master_control.update_distance_scale_latch(active, True, previous)
    assert (active, previous) == (True, True)

    active, previous = master_control.update_distance_scale_latch(active, False, previous)
    active, previous = master_control.update_distance_scale_latch(active, True, previous)
    assert (active, previous) == (False, True)


def test_distance_scale_uses_kmbox_mouse_source(monkeypatch):
    pressed_buttons = []

    class InputDevice(RecordingDevice):
        def is_down(self, button):
            pressed_buttons.append(button)
            return True

    monkeypatch.setattr(master_control, "DEVICE", InputDevice())

    assert master_control.is_distance_scale_pressed("KMBox Mouse 4", "unused")
    assert pressed_buttons == ["Mouse 4"]


def test_distance_scale_uses_local_keyboard_or_pedal(monkeypatch):
    pressed_keys = []
    monkeypatch.setattr(
        master_control.keyboard,
        "is_pressed",
        lambda key: pressed_keys.append(key) or True,
    )

    assert master_control.is_distance_scale_pressed(
        "Local keyboard / pedal", "num 1"
    )
    assert pressed_keys == ["num 1"]


def test_overlay_toggle_supports_local_and_kmbox_sources(monkeypatch):
    pressed = []
    monkeypatch.setattr(
        master_control.keyboard,
        "is_pressed",
        lambda key: pressed.append(("local", key)) or True,
    )

    class InputDevice(RecordingDevice):
        def is_down(self, button):
            pressed.append(("kmbox", button))
            return True

    monkeypatch.setattr(master_control, "DEVICE", InputDevice())

    assert master_control.is_overlay_toggle_pressed("Local keyboard / pedal", "f8")
    assert master_control.is_overlay_toggle_pressed("KMBox Mouse 5", "unused")
    assert pressed == [("local", "f8"), ("kmbox", "Mouse 5")]


def test_overlay_enabled_checkbox_controls_renderer(monkeypatch):
    calls = []
    monkeypatch.setattr(master_control, "start_overlay", lambda: calls.append("start"))
    monkeypatch.setattr(master_control, "stop_overlay", lambda: calls.append("stop"))

    master_control.callback_overlay_enabled(None, True)
    master_control.callback_overlay_enabled(None, False)

    assert calls == ["start", "stop"]


def test_reconnect_disconnects_previous_device(monkeypatch):
    previous = RecordingDevice()
    replacement = RecordingDevice()
    replacement.connect = lambda **kwargs: True
    monkeypatch.setattr(master_control, "DEVICE", previous)
    monkeypatch.setattr(master_control, "KMBoxDevice", lambda: replacement)

    connected = master_control.connect_device_from_config({
        "device_type": "KMBox",
        "kmbox_ip": "127.0.0.1",
        "kmbox_port": "8808",
        "kmbox_id": "test",
        "kmbox_monitor": 8888,
    })

    assert connected
    assert previous.disconnected
    assert master_control.DEVICE is replacement


def test_kmbox_nonzero_init_result_is_not_ready(monkeypatch):
    class FailedKMNet:
        @staticmethod
        def init(ip, port, device_id):
            return -1

        @staticmethod
        def monitor(port):
            raise AssertionError("monitor must not run after failed init")

    drain_ui_updates()
    monkeypatch.setattr(master_control, "km", FailedKMNet())
    monkeypatch.setattr(master_control, "KM_AVAILABLE", True)
    device = master_control.KMBoxDevice()

    assert not device.connect()
    assert not device.is_connected()


def test_kmbox_zero_results_mark_udp_ready(monkeypatch):
    class ReadyKMNet:
        @staticmethod
        def init(ip, port, device_id):
            return 0

        @staticmethod
        def monitor(port):
            return 0

    monkeypatch.setattr(master_control, "km", ReadyKMNet())
    monkeypatch.setattr(master_control, "KM_AVAILABLE", True)
    device = master_control.KMBoxDevice()

    assert device.connect()
    assert device.is_connected()


def test_overlay_updates_coalesce_when_command_queue_is_full(monkeypatch):
    class RunningProcess:
        @staticmethod
        def is_alive():
            return True

    command_queue = queue.Queue(maxsize=1)
    command_queue.put_nowait(("state", {"old": True}))
    monkeypatch.setattr(master_control, "OVERLAY_PROCESS", RunningProcess())
    monkeypatch.setattr(master_control, "OVERLAY_COMMAND_QUEUE", command_queue)
    master_control.OVERLAY_PENDING_UPDATES.clear()

    assert not master_control.queue_overlay_update("config", {"version": 1})
    assert not master_control.queue_overlay_update("config", {"version": 2})
    assert master_control.OVERLAY_PENDING_UPDATES == {"config": {"version": 2}}

    assert command_queue.get_nowait() == ("state", {"old": True})
    master_control.flush_overlay_updates()

    assert command_queue.get_nowait() == ("config", {"version": 2})
    assert not master_control.OVERLAY_PENDING_UPDATES


def test_kmbox_move_failure_posts_offline_status(monkeypatch):
    class FailingKMNet:
        @staticmethod
        def move(x, y):
            raise OSError("connection lost")

    drain_ui_updates()
    monkeypatch.setattr(master_control, "km", FailingKMNet())
    device = master_control.KMBoxDevice()
    device._ok = True

    device.move(1, 2)

    assert not device.is_connected()
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == ("status", False)
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == (
        "device_status",
        False,
        "KMBox move failed: connection lost",
    )


def test_kmbox_input_failure_posts_offline_status(monkeypatch):
    class FailingKMNet:
        @staticmethod
        def isdown_side2():
            raise OSError("monitor stopped")

    drain_ui_updates()
    monkeypatch.setattr(master_control, "km", FailingKMNet())
    device = master_control.KMBoxDevice()
    device._ok = True

    assert not device.is_down("Mouse 5")
    assert not device.is_connected()
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == ("status", False)
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == (
        "device_status",
        False,
        "KMBox input read failed: monitor stopped",
    )