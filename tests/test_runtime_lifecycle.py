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


def test_distance_scale_multiplier_switches_between_1x_and_2x():
    assert master_control.get_distance_scale_multiplier(False) == 1.0
    assert master_control.get_distance_scale_multiplier(True) == 2.0


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
    assert master_control.UI_UPDATE_QUEUE.get_nowait() == (
        "device_status",
        False,
        "KMBox input read failed: monitor stopped",
    )