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