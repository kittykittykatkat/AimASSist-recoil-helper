import os, sys, time, json, glob, random, queue, threading, logging, ctypes, multiprocessing
import keyboard
import dearpygui.dearpygui as dpg
from overlay_config import load_overlay_config, save_overlay_config, validate_overlay_config
from overlay_renderer import run_overlay

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
os.environ["PYTHONTIMERRESOLUTION"] = "1"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR  = os.path.join(SCRIPT_DIR, "configs")
DEVICE_FILE = os.path.join(SCRIPT_DIR, "device.json")
if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
if SCRIPT_DIR not in sys.path: sys.path.insert(0, SCRIPT_DIR)

# ---------------------------------------------------------------------------
# OPTIONAL HARDWARE MODULE IMPORTS
# ---------------------------------------------------------------------------
try:
    import kmNet as km
    KM_AVAILABLE = True
except ImportError:
    KM_AVAILABLE = False
    logging.warning("kmNet not found — KMBox unavailable.")

# ---------------------------------------------------------------------------
# DEVICE ABSTRACTION LAYER
# All hardware is accessed through DEVICE.move() and DEVICE.is_down().
# Swap in any backend without touching the hot loop.
# ---------------------------------------------------------------------------
def _win_vk(vk_code) -> bool:
    """Read a virtual-key state via Windows API. Works in fullscreen games."""
    if sys.platform.startswith('win'):
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
    return False

_BTN_VK = {
    "mouse 5": 0x06, "m5": 0x06,          # VK_XBUTTON2
    "mouse 4": 0x05, "m4": 0x05,          # VK_XBUTTON1
    "left click": 0x01, "left": 0x01,     # VK_LBUTTON
    "right click": 0x02, "right": 0x02,   # VK_RBUTTON
}

class HWDevice:
    def connect(self, **kw) -> bool: return False
    def disconnect(self): pass
    def move(self, x: int, y: int): pass
    def is_down(self, button: str) -> bool: return False
    def is_connected(self) -> bool: return False
    def name(self) -> str: return "Unknown"

class KMBoxDevice(HWDevice):
    def __init__(self):
        self._ok = False
    def connect(self, ip="192.168.2.188", port="8808", device_id="00000000", monitor_port=8888, **kw):
        if not KM_AVAILABLE:
            message = "kmNet not installed; the bundled module requires 64-bit Python 3.11."
            logging.error(message)
            post_device_status(False, message)
            return False
        try:
            init_result = km.init(ip, port, device_id)
            if init_result != 0:
                raise RuntimeError(f"kmNet init returned {init_result}")
            monitor_result = km.monitor(int(monitor_port))
            if monitor_result not in (None, 0):
                raise RuntimeError(f"kmNet monitor returned {monitor_result}")
            self._ok = True
            logging.info(f"KMBox ready (UDP unverified): {ip}:{port}")
            return True
        except Exception as e:
            self._ok = False
            message = f"KMBox connect failed: {e}"
            logging.error(message)
            post_device_status(False, message)
            return False
    def disconnect(self): self._ok = False
    def _fail(self, operation, exc):
        if not self._ok:
            return
        self._ok = False
        message = f"KMBox {operation} failed: {exc}"
        logging.error(message)
        post_device_status(False, message)
    def move(self, x, y):
        if self._ok:
            try:
                km.move(x, y)
            except Exception as exc:
                self._fail("move", exc)
    def is_down(self, button):
        if not self._ok: return False
        b = button.lower()
        try:
            if b in ("mouse 5", "m5"):      return km.isdown_side2() == 1
            if b in ("mouse 4", "m4"):      return km.isdown_side1() == 1
            if b in ("left click", "left"): return km.isdown_left()  == 1
            if b in ("right click","right"):return km.isdown_right() == 1
        except Exception as exc:
            self._fail("input read", exc)
        return False
    def is_connected(self): return self._ok
    def name(self): return "KMBox"

class MakcuDevice(HWDevice):
    """
    Makcu / MAKCU adapter.
    Fill in the two TODO blocks with your makcu library's actual calls.
    Button reads fall back to Windows API (works in fullscreen games).
    """
    def __init__(self):
        self._ok  = False
        self._dev = None
    def connect(self, com_port="COM3", baud_rate=115200, **kw):
        try:
            # ── TODO: replace with your makcu library connect call ──────────
            # Example A (official makcu lib):
            #   from makcu import Makcu
            #   self._dev = Makcu(com_port)
            # Example B (raw serial):
            #   import serial
            #   self._dev = serial.Serial(com_port, int(baud_rate), timeout=0.01)
            # ────────────────────────────────────────────────────────────────
            raise NotImplementedError("Fill in makcu connect — see TODO above")
        except NotImplementedError as e:
            logging.error(f"Makcu: {e}")
            self._ok = False
            return False
        except Exception as e:
            logging.error(f"Makcu connect failed ({com_port}): {e}")
            self._ok = False
            return False
        self._ok = True
        logging.info(f"Makcu connected: {com_port}")
        return True
    def disconnect(self):
        try:
            if self._dev: self._dev.close()
        except: pass
        self._ok = False
    def move(self, x, y):
        if not self._ok or (not x and not y): return
        try:
            # ── TODO: replace with your makcu library move call ─────────────
            # Example A:  self._dev.move(x, y)
            # Example B (serial packet):
            #   import struct
            #   self._dev.write(struct.pack('<bbb', 0x01, x & 0xFF, y & 0xFF))
            # ────────────────────────────────────────────────────────────────
            pass
        except Exception as e:
            logging.error(f"Makcu move failed: {e}")
            self._ok = False
    def is_down(self, button):
        # Makcu doesn't report button state to host; use Windows API fallback.
        b = button.lower()
        vk = _BTN_VK.get(b)
        if vk: return _win_vk(vk)
        return keyboard.is_pressed(b) if b else False
    def is_connected(self): return self._ok
    def name(self): return "Makcu"

class SimDevice(HWDevice):
    """No hardware — keyboard/Win32 fallback for testing."""
    def connect(self, **kw): return True
    def move(self, x, y): pass
    def is_down(self, button):
        b = button.lower()
        vk = _BTN_VK.get(b)
        if vk: return _win_vk(vk)
        return keyboard.is_pressed(b) if b else False
    def is_connected(self): return True
    def name(self): return "Simulation"

# Global device instance — swapped out by connect_device_from_config()
DEVICE: HWDevice = SimDevice()

# ---------------------------------------------------------------------------
# DEVICE CONFIG  (device.json — separate from weapon profiles)
# ---------------------------------------------------------------------------
_DEV_DEFAULTS = {
    "device_type":      "KMBox",
    "kmbox_ip":         "192.168.2.188",
    "kmbox_port":       "8808",
    "kmbox_id":         "00000000",
    "kmbox_monitor":    8888,
    "makcu_com":        "COM3",
    "makcu_baud":       115200,
}

def load_device_config() -> dict:
    if os.path.exists(DEVICE_FILE):
        try:
            with open(DEVICE_FILE) as f:
                return {**_DEV_DEFAULTS, **json.load(f)}
        except Exception as e:
            logging.warning(f"device.json load failed: {e}")
    return _DEV_DEFAULTS.copy()

def save_device_config(cfg: dict):
    try:
        with open(DEVICE_FILE, "w") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        logging.error(f"device.json save failed: {e}")

def connect_device_from_config(cfg: dict) -> bool:
    global DEVICE
    previous_device = DEVICE
    dtype = cfg.get("device_type", "KMBox")
    if dtype == "KMBox":
        new_device = KMBoxDevice()
        connected = new_device.connect(
            ip=cfg["kmbox_ip"], port=cfg["kmbox_port"],
            device_id=cfg["kmbox_id"], monitor_port=cfg["kmbox_monitor"]
        )
    elif dtype == "Makcu":
        new_device = MakcuDevice()
        connected = new_device.connect(
            com_port=cfg["makcu_com"], baud_rate=cfg["makcu_baud"]
        )
    else:
        new_device = SimDevice()
        connected = new_device.connect()
    try:
        previous_device.disconnect()
    except Exception as exc:
        logging.warning(f"Previous device disconnect failed: {exc}")
    DEVICE = new_device
    return connected

def get_available_com_ports() -> list:
    try:
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        return ports if ports else ["No ports found"]
    except ImportError:
        return ["Install pyserial for auto-detect"]

# ---------------------------------------------------------------------------
# GLOBAL QUEUES + LOCK
# maxsize=16 so rapid multi-slider changes don't silently drop each other
# ---------------------------------------------------------------------------
DATA_QUEUE      = queue.Queue(maxsize=16)
STATE_LOCK      = threading.Lock()
UI_UPDATE_QUEUE = queue.Queue(maxsize=32)

KS_KEY_OPTIONS = ["None", "Mouse 5", "Mouse 4", "Left Click", "Right Click"]
DISTANCE_SCALE_SOURCES = ["KMBox Mouse 5", "KMBox Mouse 4", "Local keyboard / pedal"]

def post_device_status(connected, message):
    """Queue a device state change for DearPyGui's main thread."""
    try:
        UI_UPDATE_QUEUE.put_nowait(("device_status", connected, message))
    except queue.Full:
        logging.error(f"Device status update dropped: {message}")

def is_distance_scale_pressed(source, local_key):
    """Read the configured 2x toggle from KMBox or a local keyboard HID."""
    if source == "KMBox Mouse 5":
        return DEVICE.is_down("Mouse 5")
    if source == "KMBox Mouse 4":
        return DEVICE.is_down("Mouse 4")
    return keyboard.is_pressed(local_key) if local_key else False

def is_overlay_toggle_pressed(source, local_key):
    """Read the overlay toggle from a local HID or KMBox mouse button."""
    if source == "Local keyboard / pedal":
        return keyboard.is_pressed(local_key) if local_key else False
    return is_distance_scale_pressed(source, "")

# ---------------------------------------------------------------------------
# RUNTIME STATE
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "master_active":         True,
    "active_tab":            "Recoil",
    "recoil_module_enabled": True,
    "burst_module_enabled":  True,

    "recoil_trigger_key": "Mouse 5",
    "burst_trigger_key":  "Mouse 4",
    "recoil_require_ads": False,
    "burst_require_ads":  False,
    "recoil_is_toggle":   False,
    "burst_is_toggle":    False,
    "recoil_ks_key":      "None",
    "burst_ks_key":       "None",
    "toggle_key":         "/",

    "local_sens":       20.0,
    "local_zoom_mult":  1.00,
    "local_fov":        100,

    "recoil_nodes":       [[0.0, 0.0, 0.0]],
    "recoil_scale_x":     1.0,
    "recoil_scale_y":     1.0,
    "recoil_jitter":      0.05,
    "time_step_interval": 0.15,
    "overlay_mode":       "None",
    "distance_scale_enabled":   False,
    "distance_scale_source":    "Local keyboard / pedal",
    "distance_scale_local_key": "num 1",
    "distance_scale_2x_active": False,
    "far_scale_x":              2.0,
    "far_scale_y":              2.0,
    "far_scale_linked":         False,

    "burst_count":           3,
    "burst_y_pull":          14.0,
    "burst_x_pull":          0.0,
    "burst_intra_delay_ms":  60.0,
    "burst_inter_delay_ms":  275.0,

    "hw_killswitch_enabled": False,
    "hw_killswitch_key":     "Mouse 5",
}

OVERLAY_CONFIG = load_overlay_config()
OVERLAY_PROCESS = None
OVERLAY_COMMAND_QUEUE = None
OVERLAY_STATUS_QUEUE = None
OVERLAY_PENDING_UPDATES = {}
DEVICE_CONNECT_LOCK = threading.Lock()
DEVICE_CONNECT_COOLDOWN = 1.0
_last_device_connect_time = 0.0

OVERLAY_COLOR_PALETTE = {
    "Green":  [0, 210, 120],
    "Cyan":   [0, 190, 255],
    "Blue":   [55, 110, 255],
    "Purple": [155, 70, 240],
    "Orange": [255, 170, 40],
    "Red":    [239, 68, 68],
    "White":  [235, 235, 240],
    "Gray":   [70, 70, 82],
}
OVERLAY_TOGGLE_SOURCES = ["Local keyboard / pedal", "KMBox Mouse 4", "KMBox Mouse 5"]
OVERLAY_LAYOUT_W, OVERLAY_LAYOUT_H = 560, 260
_overlay_drag = {"name": None, "last": None}

# ---------------------------------------------------------------------------
# DARK TITLEBAR
# ---------------------------------------------------------------------------
def _apply_dark_titlebar_worker(stop_event=None):
    if not sys.platform.startswith('win'): return
    if stop_event:
        if stop_event.wait(0.3): return
    else:
        time.sleep(0.3)
    for _ in range(30):
        if stop_event and stop_event.is_set(): return
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "AimASSist Control Workspace")
            if hwnd:
                val = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
                logging.info("Dark title bar applied.")
                return
        except Exception: pass
        if stop_event:
            if stop_event.wait(0.1): return
        else:
            time.sleep(0.1)

# ---------------------------------------------------------------------------
# PC KEYBOARD PANIC LISTENER
# ---------------------------------------------------------------------------
def main_pc_keyboard_listener_worker(stop_event=None):
    latch = False
    overlay_latch = False
    while not stop_event or not stop_event.is_set():
        try:
            with STATE_LOCK:
                target = DEFAULT_STATE["toggle_key"].lower()
            if keyboard.is_pressed(target):
                if not latch:
                    latch = True
                    with STATE_LOCK:
                        DEFAULT_STATE["master_active"] = not DEFAULT_STATE["master_active"]
                        active = DEFAULT_STATE["master_active"]
                    try: UI_UPDATE_QUEUE.put_nowait(("status", active))
                    except queue.Full: pass
                    logging.info(f"PC panic: {'ONLINE' if active else 'PAUSED'}")
            else:
                latch = False
            overlay_source = OVERLAY_CONFIG.get("toggle_source", "Local keyboard / pedal")
            overlay_pressed = overlay_source == "Local keyboard / pedal" and is_overlay_toggle_pressed(
                overlay_source, OVERLAY_CONFIG.get("toggle_key", "f8")
            )
            if overlay_pressed:
                if not overlay_latch:
                    overlay_latch = True
                    try: UI_UPDATE_QUEUE.put_nowait(("overlay_toggle",))
                    except queue.Full: pass
            else:
                overlay_latch = False
        except Exception: pass
        if stop_event:
            stop_event.wait(0.01)
        else:
            time.sleep(0.01)

def callback_update_hotkey(sender, app_data):
    with STATE_LOCK: DEFAULT_STATE["toggle_key"] = app_data
    ui_thread_push_sync(sender, app_data, "toggle_key")

# ---------------------------------------------------------------------------
# INTERPOLATION  (takes a PRE-SORTED list — caller maintains the cache)
# ---------------------------------------------------------------------------
def get_interpolated_velocity(elapsed_time, sorted_nodes):
    sn = sorted_nodes
    if not sn or len(sn) < 2: return 0.0, 0.0
    if elapsed_time >= sn[-1][0]: return 0.0, 0.0
    if elapsed_time <= sn[0][0]:  return sn[0][1], sn[0][2]
    for i in range(len(sn) - 1):
        a, b = sn[i], sn[i + 1]
        if a[0] <= elapsed_time <= b[0]:
            d = b[0] - a[0]
            if d == 0: return a[1], a[2]
            t = (elapsed_time - a[0]) / d
            return a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t
    return 0.0, 0.0

def select_runtime_mode(state, recoil_triggered, burst_triggered, ads, burst_in_progress=False):
    """Select output from enabled modules independently of the visible UI tab."""
    recoil_ready = (
        state["recoil_module_enabled"]
        and recoil_triggered
        and (not state["recoil_require_ads"] or ads)
    )
    burst_ready = (
        state["burst_module_enabled"]
        and burst_triggered
        and (not state["burst_require_ads"] or ads)
    )
    if recoil_ready:
        return "Recoil", True
    if burst_ready or (state["burst_module_enabled"] and burst_in_progress):
        return "Burst", burst_ready
    return "None", False

def get_far_scale_multipliers(far_mode_active, far_scale_x, far_scale_y):
    """Return independent runtime recoil multipliers for base or Far mode."""
    if not far_mode_active:
        return 1.0, 1.0
    return far_scale_x, far_scale_y

def snap_far_scale(value):
    """Clamp Far-mode recoil scaling to 0.05 increments."""
    return round(max(0.5, min(2.5, round(float(value) / 0.05) * 0.05)), 2)

def update_distance_scale_latch(scale_2x_active, pressed, previously_pressed):
    """Toggle distance scale once on each input press edge."""
    if pressed and not previously_pressed:
        scale_2x_active = not scale_2x_active
    return scale_2x_active, pressed

# ---------------------------------------------------------------------------
# CONFIG I/O
# ---------------------------------------------------------------------------
def get_config_files():
    files = [os.path.basename(f) for f in glob.glob(os.path.join(CONFIG_DIR, "*.json"))]
    return files if files else ["No configs found"]

def callback_save_config(sender, app_data):
    filename = dpg.get_value("ui_save_name")
    if not filename: return
    if not filename.endswith(".json"): filename += ".json"
    blob = {
        "recoil_module_enabled":  dpg.get_value("ui_toggle_recoil_mod"),
        "burst_module_enabled":   dpg.get_value("ui_toggle_burst_mod"),
        "recoil_trigger_key":     dpg.get_value("ui_recoil_trigger_combo"),
        "burst_trigger_key":      dpg.get_value("ui_burst_trigger_combo"),
        "recoil_require_ads":     dpg.get_value("ui_recoil_req_ads"),
        "burst_require_ads":      dpg.get_value("ui_burst_req_ads"),
        "recoil_is_toggle":       dpg.get_value("ui_recoil_is_toggle"),
        "burst_is_toggle":        dpg.get_value("ui_burst_is_toggle"),
        "recoil_ks_key":          dpg.get_value("ui_recoil_ks_key"),
        "burst_ks_key":           dpg.get_value("ui_burst_ks_key"),
        "toggle_key":             dpg.get_value("ui_toggle_combo"),
        "local_sens":             dpg.get_value("ui_input_sens"),
        "local_zoom_mult":        dpg.get_value("ui_input_zoom_mult"),
        "local_fov":              dpg.get_value("ui_input_fov"),
        "recoil_scale_x":         dpg.get_value("ui_recoil_scale_x"),
        "recoil_scale_y":         dpg.get_value("ui_recoil_scale_y"),
        "recoil_jitter":          dpg.get_value("ui_recoil_jitter"),
        "time_step_interval":     dpg.get_value("ui_time_interval"),
        "overlay_mode":           dpg.get_value("ui_overlay_combo"),
        "distance_scale_enabled": dpg.get_value("ui_distance_scale_enabled"),
        "distance_scale_source":  dpg.get_value("ui_distance_scale_source"),
        "distance_scale_local_key": dpg.get_value("ui_distance_scale_local_key"),
        "far_scale_x":            dpg.get_value("ui_far_scale_x"),
        "far_scale_y":            dpg.get_value("ui_far_scale_y"),
        "far_scale_linked":       dpg.get_value("ui_far_scale_linked"),
        "recoil_nodes":           DEFAULT_STATE["recoil_nodes"],
        "burst_count":            dpg.get_value("ui_burst_count"),
        "burst_y_pull":           dpg.get_value("ui_burst_pull"),
        "burst_x_pull":           dpg.get_value("ui_burst_x"),
        "burst_intra_delay_ms":   dpg.get_value("ui_burst_intra_ms"),
        "burst_inter_delay_ms":   dpg.get_value("ui_burst_inter_ms"),
        "hw_killswitch_enabled":  dpg.get_value("ui_hw_ks_enabled"),
        "hw_killswitch_key":      dpg.get_value("ui_hw_ks_key_combo"),
    }
    with open(os.path.join(CONFIG_DIR, filename), "w") as f:
        json.dump(blob, f, indent=4)
    logging.info(f"Saved: {filename}")
    dpg.configure_item("ui_config_selector", items=get_config_files())

def callback_load_config(sender, app_data):
    filename = dpg.get_value("ui_config_selector")
    if filename in ["No configs found", "Select Profile", None]: return
    try:
        with open(os.path.join(CONFIG_DIR, filename)) as f:
            data = json.load(f)
        dpg.set_value("ui_toggle_recoil_mod",   data.get("recoil_module_enabled", True))
        dpg.set_value("ui_toggle_burst_mod",     data.get("burst_module_enabled",  True))
        dpg.set_value("ui_recoil_trigger_combo", data.get("recoil_trigger_key", "Mouse 5"))
        dpg.set_value("ui_burst_trigger_combo",  data.get("burst_trigger_key",  "Mouse 4"))
        dpg.set_value("ui_recoil_req_ads",       data.get("recoil_require_ads", False))
        dpg.set_value("ui_burst_req_ads",        data.get("burst_require_ads",  False))
        dpg.set_value("ui_recoil_is_toggle",     data.get("recoil_is_toggle",   False))
        dpg.set_value("ui_burst_is_toggle",      data.get("burst_is_toggle",    False))
        dpg.set_value("ui_recoil_ks_key",        data.get("recoil_ks_key",      "None"))
        dpg.set_value("ui_burst_ks_key",         data.get("burst_ks_key",       "None"))
        dpg.set_value("ui_toggle_combo",         data.get("toggle_key",         "/"))
        dpg.set_value("ui_input_sens",           data.get("local_sens",         22.0))
        dpg.set_value("ui_input_zoom_mult",      data.get("local_zoom_mult",    0.75))
        dpg.set_value("ui_input_fov",            data.get("local_fov",          100))
        dpg.set_value("ui_recoil_scale_x",       data.get("recoil_scale_x",     1.0))
        dpg.set_value("ui_recoil_scale_y",       data.get("recoil_scale_y",     1.0))
        dpg.set_value("ui_recoil_jitter",        data.get("recoil_jitter",      0.05))
        dpg.set_value("ui_time_interval",        data.get("time_step_interval", 0.15))
        dpg.set_value("ui_overlay_combo",        data.get("overlay_mode",       "None"))
        dpg.set_value("ui_distance_scale_enabled", data.get("distance_scale_enabled", False))
        dpg.set_value("ui_distance_scale_source", data.get("distance_scale_source", "Local keyboard / pedal"))
        dpg.set_value("ui_distance_scale_local_key", data.get("distance_scale_local_key", "num 1"))
        dpg.set_value("ui_far_scale_x",          data.get("far_scale_x", 2.0))
        dpg.set_value("ui_far_scale_y",          data.get("far_scale_y", 2.0))
        dpg.set_value("ui_far_scale_linked",     data.get("far_scale_linked", False))
        data["far_scale_x"] = data.get("far_scale_x", 2.0)
        data["far_scale_y"] = data.get("far_scale_y", 2.0)
        data["far_scale_linked"] = data.get("far_scale_linked", False)
        callback_distance_scale_source(None, data.get("distance_scale_source", "Local keyboard / pedal"))
        dpg.set_value("ui_burst_count",          data.get("burst_count",        3))
        dpg.set_value("ui_burst_pull",           data.get("burst_y_pull",       14.0))
        dpg.set_value("ui_burst_x",              data.get("burst_x_pull",       0.0))
        dpg.set_value("ui_burst_intra_ms",       data.get("burst_intra_delay_ms",  60.0))
        dpg.set_value("ui_burst_inter_ms",       data.get("burst_inter_delay_ms", 275.0))
        dpg.set_value("ui_hw_ks_enabled",        data.get("hw_killswitch_enabled", False))
        dpg.set_value("ui_hw_ks_key_combo",      data.get("hw_killswitch_key",  "Mouse 5"))
        DEFAULT_STATE["recoil_nodes"] = data.get("recoil_nodes", [[0.0, 0.0, 0.0]])
        data["distance_scale_2x_active"] = False
        # Push full blob — maxsize=16 means this won't stomp a simultaneous change
        try: DATA_QUEUE.put_nowait(data)
        except queue.Full: pass
        with STATE_LOCK:
            DEFAULT_STATE["recoil_module_enabled"] = data.get("recoil_module_enabled", True)
            DEFAULT_STATE["burst_module_enabled"]  = data.get("burst_module_enabled", True)
            DEFAULT_STATE["toggle_key"]            = data.get("toggle_key", "/")
            DEFAULT_STATE["hw_killswitch_enabled"] = data.get("hw_killswitch_enabled", False)
            DEFAULT_STATE["hw_killswitch_key"]     = data.get("hw_killswitch_key", "Mouse 5")
            DEFAULT_STATE["distance_scale_2x_active"] = False
        _update_distance_scale_ui(False)
        send_overlay_state()
        redraw_recoil_canvas()
        redraw_burst_canvas()
        logging.info(f"Loaded: {filename}")
    except Exception as e:
        logging.error(f"Load failed: {e}")

# ---------------------------------------------------------------------------
# SPIN SLEEP — hybrid: OS sleep most of it, spin the last 200µs
# Keeps precision without burning 100% of one core
# ---------------------------------------------------------------------------
def precision_sleep(duration):
    end = time.perf_counter() + duration
    spin_threshold = end - 0.0002
    if spin_threshold > time.perf_counter():
        time.sleep(max(0, spin_threshold - time.perf_counter()))
    while time.perf_counter() < end:
        pass

# ---------------------------------------------------------------------------
# HARDWARE ENGINE
# ---------------------------------------------------------------------------
def hardware_consumer_engine(data_mailbox, stop_event=None):
    rs = DEFAULT_STATE.copy()

    recoil_trigger_latch = False
    start_burst_time     = 0.0
    in_burst_sequence    = False
    burst_seq_start      = 0.0
    shots_in_seq         = 0
    last_burst_finish    = 0.0
    accum_x = accum_y    = 0.0
    prev_r_phys          = False
    recoil_toggled_on    = False
    prev_b_phys          = False
    burst_toggled_on     = False
    r_ks_prev            = False
    b_ks_prev            = False
    hw_ks_prev           = False
    distance_scale_prev  = False
    overlay_toggle_prev  = False

    # Pre-sorted nodes cache — only re-sorts when the list object changes
    _nodes_sorted   = []
    _nodes_list_ref = None

    def key(k: str) -> bool:
        if not k or k == "None": return False
        return DEVICE.is_down(k)

    def ui_post(tag, value):
        try: UI_UPDATE_QUEUE.put_nowait(("set_value", tag, value))
        except queue.Full: pass
        if tag in ("ui_toggle_recoil_mod", "ui_toggle_burst_mod"):
            try: UI_UPDATE_QUEUE.put_nowait(("runtime_state",))
            except queue.Full: pass

    while not stop_event or not stop_event.is_set():
        try:
            # Drain config updates (maxsize=16 — no silent drops on rapid changes)
            while True:
                try: rs.update(data_mailbox.get_nowait())
                except queue.Empty: break

            with STATE_LOCK:
                is_active = DEFAULT_STATE["master_active"]
                hw_ks_on  = DEFAULT_STATE["hw_killswitch_enabled"]
                hw_ks_key = DEFAULT_STATE["hw_killswitch_key"]
                if is_active:
                    raw_nodes = DEFAULT_STATE["recoil_nodes"]

            # Pre-sorted nodes cache — re-sort only when list object changes
            if is_active and raw_nodes is not _nodes_list_ref:
                _nodes_sorted   = sorted(raw_nodes, key=lambda n: n[0])
                _nodes_list_ref = raw_nodes

            # -- PER-TAB MODULE KILLSWITCHES (run even when paused) --
            r_ks = rs["recoil_ks_key"]
            if r_ks != "None":
                r_ks_c = key(r_ks)
                if r_ks_c and not r_ks_prev:
                    new = not rs["recoil_module_enabled"]
                    rs["recoil_module_enabled"] = new
                    with STATE_LOCK: DEFAULT_STATE["recoil_module_enabled"] = new
                    if not new:
                        recoil_trigger_latch = False
                        recoil_toggled_on    = False
                    ui_post("ui_toggle_recoil_mod", new)
                    logging.info(f"Recoil: {'ON' if new else 'OFF'}")
                r_ks_prev = r_ks_c
            else:
                r_ks_prev = False

            b_ks = rs["burst_ks_key"]
            if b_ks != "None":
                b_ks_c = key(b_ks)
                if b_ks_c and not b_ks_prev:
                    new = not rs["burst_module_enabled"]
                    rs["burst_module_enabled"] = new
                    with STATE_LOCK: DEFAULT_STATE["burst_module_enabled"] = new
                    if not new:
                        in_burst_sequence = False
                        burst_toggled_on  = False
                    ui_post("ui_toggle_burst_mod", new)
                    logging.info(f"Burst: {'ON' if new else 'OFF'}")
                b_ks_prev = b_ks_c
            else:
                b_ks_prev = False

            # -- GLOBAL HW KILLSWITCH --
            if hw_ks_on:
                hw_c = key(hw_ks_key)
                if hw_c and not hw_ks_prev:
                    with STATE_LOCK:
                        DEFAULT_STATE["master_active"] = not DEFAULT_STATE["master_active"]
                        is_active = DEFAULT_STATE["master_active"]
                    try: UI_UPDATE_QUEUE.put_nowait(("status", is_active))
                    except queue.Full: pass
                hw_ks_prev = hw_c
            else:
                hw_ks_prev = False

            overlay_source = OVERLAY_CONFIG.get("toggle_source", "Local keyboard / pedal")
            if overlay_source != "Local keyboard / pedal":
                overlay_pressed = is_overlay_toggle_pressed(overlay_source, "")
                if overlay_pressed and not overlay_toggle_prev:
                    try: UI_UPDATE_QUEUE.put_nowait(("overlay_toggle",))
                    except queue.Full: pass
                overlay_toggle_prev = overlay_pressed
            else:
                overlay_toggle_prev = False

            if not is_active:
                in_burst_sequence    = False
                recoil_trigger_latch = False
                recoil_toggled_on    = False
                burst_toggled_on     = False
                time.sleep(0.01)
                continue

            if rs["distance_scale_enabled"]:
                scale_pressed = is_distance_scale_pressed(
                    rs["distance_scale_source"], rs["distance_scale_local_key"]
                )
                scale_2x, next_scale_prev = update_distance_scale_latch(
                    rs["distance_scale_2x_active"], scale_pressed, distance_scale_prev
                )
                if scale_2x != rs["distance_scale_2x_active"]:
                    rs["distance_scale_2x_active"] = scale_2x
                    with STATE_LOCK:
                        DEFAULT_STATE["distance_scale_2x_active"] = scale_2x
                    try:
                        UI_UPDATE_QUEUE.put_nowait(("distance_scale", scale_2x))
                    except queue.Full:
                        logging.warning("Distance scale UI update dropped")
                    logging.info(f"Distance scale: {'50 m / 2x' if scale_2x else '25 m / 1x'}")
                distance_scale_prev = next_scale_prev
            else:
                distance_scale_prev = False

            # -- HOT PATH --
            now     = time.perf_counter()
            fov_mod = 90.0 / rs["local_fov"]
            ads     = key("right click")

            r_phys = key(rs["recoil_trigger_key"])
            if rs["recoil_is_toggle"]:
                if r_phys and not prev_r_phys: recoil_toggled_on = not recoil_toggled_on
                raw_r = recoil_toggled_on
            else:
                raw_r = r_phys; recoil_toggled_on = False
            prev_r_phys = r_phys

            b_phys = key(rs["burst_trigger_key"])
            if rs["burst_is_toggle"]:
                if b_phys and not prev_b_phys: burst_toggled_on = not burst_toggled_on
                raw_b = burst_toggled_on
            else:
                raw_b = b_phys; burst_toggled_on = False
            prev_b_phys = b_phys

            active_mode, is_firing = select_runtime_mode(
                rs, raw_r, raw_b, ads, in_burst_sequence
            )

            if in_burst_sequence and rs["burst_require_ads"] and not ads:
                in_burst_sequence = False; last_burst_finish = now
            if in_burst_sequence and active_mode != "Burst":
                in_burst_sequence = False; last_burst_finish = now

            if is_firing or in_burst_sequence:
                zm       = rs["local_zoom_mult"] if ads else 1.0
                sens_mod = 22.0 / (rs["local_sens"] * zm)

                if active_mode == "Recoil":
                    if not recoil_trigger_latch:
                        recoil_trigger_latch = True
                        start_burst_time     = now
                    vx, vy = get_interpolated_velocity(now - start_burst_time, _nodes_sorted)
                    far_x, far_y = get_far_scale_multipliers(
                        rs["distance_scale_2x_active"], rs["far_scale_x"], rs["far_scale_y"]
                    )
                    fx = vx * rs["recoil_scale_x"] * far_x * fov_mod * sens_mod
                    fy = vy * rs["recoil_scale_y"] * far_y * fov_mod * sens_mod
                    if rs["recoil_jitter"] > 0:
                        fx += random.uniform(-rs["recoil_jitter"], rs["recoil_jitter"]) * 5
                    accum_x += fx; accum_y += fy
                    if abs(accum_x) >= 1.0 or abs(accum_y) >= 1.0:
                        mx, my = int(accum_x), int(accum_y)
                        if mx or my: DEVICE.move(mx, my)
                        accum_x -= mx; accum_y -= my

                elif active_mode == "Burst":
                    if is_firing and not in_burst_sequence:
                        if (now - last_burst_finish) >= rs["burst_inter_delay_ms"] / 1000.0:
                            in_burst_sequence = True
                            burst_seq_start   = now
                            shots_in_seq      = 0
                    if in_burst_sequence:
                        t_ms        = (now - burst_seq_start) * 1000.0
                        target_shot = min(int(t_ms // rs["burst_intra_delay_ms"]) + 1, rs["burst_count"])
                        if target_shot > shots_in_seq:
                            DEVICE.move(int(rs["burst_x_pull"] * fov_mod * sens_mod),
                                        int(rs["burst_y_pull"] * fov_mod * sens_mod))
                            shots_in_seq = target_shot
                        if shots_in_seq >= rs["burst_count"]:
                            in_burst_sequence = False
                            last_burst_finish = time.perf_counter()
            else:
                recoil_trigger_latch = False

            precision_sleep(0.001)
        except Exception as exc:
            logging.debug(f"HW thread exception: {exc}")


# ---------------------------------------------------------------------------
# CANVAS — auto-zoom, node placement, drag, right-click delete
# ---------------------------------------------------------------------------
CANVAS_W, CANVAS_H = 590, 340
CANVAS_PAD = 35
NODE_HIT_RADIUS = 14

_drag = {"active": False, "idx": -1, "last": None, "scale": 1.0}
_canvas_cache = {"pts": [], "scale": 1.0, "origin": (CANVAS_W // 2, 40)}
_selected_idx = -1
_user_zoom = 1.0   # multiplier on top of auto-fit


def _compute_canvas_layout():
    """Auto-zoom: compute screen positions for all nodes to fit the canvas."""
    nodes = DEFAULT_STATE["recoil_nodes"]
    empty = len(nodes) <= 1 and nodes[0][1] == 0.0 and nodes[0][2] == 0.0
    fallback_origin = (CANVAS_W // 2, CANVAS_PAD + 10)
    if not nodes or empty:
        _canvas_cache.update(pts=[], scale=1.0, origin=fallback_origin)
        return [], 1.0, fallback_origin

    cum_x, cum_y = [0.0], [0.0]
    for n in nodes:
        cum_x.append(cum_x[-1] + n[1])
        cum_y.append(cum_y[-1] + n[2])

    min_x, max_x = min(cum_x), max(cum_x)
    min_y, max_y = min(cum_y), max(cum_y)
    range_x = max(max_x - min_x, 0.3)
    range_y = max(max_y - min_y, 0.3)
    usable_w = CANVAS_W - 2 * CANVAS_PAD
    usable_h = CANVAS_H - 2 * CANVAS_PAD
    scale = min(usable_w / range_x, usable_h / range_y) * _user_zoom
    pattern_w = range_x * scale
    pattern_h = range_y * scale
    offset_x = CANVAS_PAD + (usable_w - pattern_w) / 2
    offset_y = CANVAS_PAD + (usable_h - pattern_h) / 2
    ox = offset_x + (-min_x) * scale
    oy = offset_y + (-min_y) * scale

    pts = []
    for i in range(len(nodes)):
        sx = int(ox + cum_x[i + 1] * scale)
        sy = int(oy + cum_y[i + 1] * scale)
        sx = max(4, min(CANVAS_W - 4, sx))
        sy = max(4, min(CANVAS_H - 4, sy))
        pts.append((sx, sy))

    origin = (int(ox), int(oy))
    _canvas_cache.update(pts=pts, scale=scale, origin=origin)
    return pts, scale, origin


def _find_node_near(canvas_pos):
    mx, my = canvas_pos
    pts = _canvas_cache["pts"]
    for i, (px, py) in enumerate(pts):
        if (mx - px) ** 2 + (my - py) ** 2 < NODE_HIT_RADIUS ** 2:
            return i
    return -1


def _recalc_node_times():
    iv = dpg.get_value("ui_time_interval")
    for i, n in enumerate(DEFAULT_STATE["recoil_nodes"]):
        n[0] = round(i * iv, 4)


def _update_node_info():
    nodes = DEFAULT_STATE["recoil_nodes"]
    count = len(nodes)
    if not dpg.does_item_exist("ui_node_count_text"):
        return
    if count <= 1 and nodes[0][1] == 0.0 and nodes[0][2] == 0.0:
        dpg.set_value("ui_node_count_text", "Empty \u2014 click canvas or import a .txt")
        return
    iv = dpg.get_value("ui_time_interval") or 0.1
    duration = count * iv
    total_x = sum(n[1] for n in nodes)
    total_y = sum(n[2] for n in nodes)
    dpg.set_value("ui_node_count_text",
                  f"{count} nodes  |  {duration:.2f}s  |  drift X {total_x:+.1f}  Y {total_y:+.1f}")


def _screen_to_logical(sx, sy):
    origin = _canvas_cache["origin"]
    scale = _canvas_cache["scale"]
    if scale < 0.001:
        return 0.0, 0.0
    return (sx - origin[0]) / scale, (sy - origin[1]) / scale


def _update_selected_ui():
    """Update the selected node editor fields."""
    global _selected_idx
    nodes = DEFAULT_STATE["recoil_nodes"]
    if _selected_idx < 0 or _selected_idx >= len(nodes):
        _selected_idx = -1
    if not dpg.does_item_exist("ui_sel_label"):
        return
    if _selected_idx < 0:
        dpg.set_value("ui_sel_label", "No selection")
        dpg.configure_item("ui_sel_label", color=(55, 55, 70))
        if dpg.does_item_exist("ui_sel_vx"):
            dpg.set_value("ui_sel_vx", 0.0)
            dpg.set_value("ui_sel_vy", 0.0)
    else:
        n = nodes[_selected_idx]
        dpg.set_value("ui_sel_label", f"Node #{_selected_idx + 1}/{len(nodes)}")
        dpg.configure_item("ui_sel_label", color=(0, 200, 120))
        if dpg.does_item_exist("ui_sel_vx"):
            dpg.set_value("ui_sel_vx", n[1])
            dpg.set_value("ui_sel_vy", n[2])


def callback_edit_sel_vx(sender, app_data):
    global _selected_idx
    nodes = DEFAULT_STATE["recoil_nodes"]
    if 0 <= _selected_idx < len(nodes):
        nodes[_selected_idx][1] = app_data
        redraw_recoil_canvas()
        _update_node_info()


def callback_edit_sel_vy(sender, app_data):
    global _selected_idx
    nodes = DEFAULT_STATE["recoil_nodes"]
    if 0 <= _selected_idx < len(nodes):
        nodes[_selected_idx][2] = app_data
        redraw_recoil_canvas()
        _update_node_info()


def callback_delete_selected(sender, app_data):
    global _selected_idx
    nodes = DEFAULT_STATE["recoil_nodes"]
    if _selected_idx < 0 or _selected_idx >= len(nodes) or len(nodes) <= 1:
        return
    nodes.pop(_selected_idx)
    _recalc_node_times()
    if _selected_idx >= len(nodes):
        _selected_idx = len(nodes) - 1
    redraw_recoil_canvas()
    _update_node_info()
    _update_selected_ui()


def callback_zoom_in(sender, app_data):
    global _user_zoom
    _user_zoom = min(_user_zoom * 1.4, 20.0)
    redraw_recoil_canvas()


def callback_zoom_out(sender, app_data):
    global _user_zoom
    _user_zoom = max(_user_zoom / 1.4, 0.1)
    redraw_recoil_canvas()


def callback_zoom_fit(sender, app_data):
    global _user_zoom
    _user_zoom = 1.0
    redraw_recoil_canvas()


def callback_canvas_left_click(sender, app_data):
    global _selected_idx
    pos = dpg.get_drawing_mouse_pos()
    idx = _find_node_near(pos)
    if idx >= 0:
        # Click on node = select it + start drag
        _selected_idx = idx
        _drag.update(active=True, idx=idx, last=pos, scale=_canvas_cache["scale"])
        redraw_recoil_canvas()
        _update_selected_ui()
        return
    # Click on empty = add node
    lx, ly = _screen_to_logical(pos[0], pos[1])
    nodes = DEFAULT_STATE["recoil_nodes"]
    cum_x = sum(n[1] for n in nodes)
    cum_y = sum(n[2] for n in nodes)
    dx = lx - cum_x
    dy = ly - cum_y
    iv = dpg.get_value("ui_time_interval")
    if len(nodes) == 1 and nodes[0][1] == 0.0 and nodes[0][2] == 0.0:
        DEFAULT_STATE["recoil_nodes"] = [[0.0, dx, dy]]
        _selected_idx = 0
    else:
        DEFAULT_STATE["recoil_nodes"].append([round(len(nodes) * iv, 4), dx, dy])
        _selected_idx = len(DEFAULT_STATE["recoil_nodes"]) - 1
    redraw_recoil_canvas()
    _update_node_info()
    _update_selected_ui()


def callback_canvas_right_click(sender, app_data):
    """Right-click on node = select it (without adding)."""
    global _selected_idx
    pos = dpg.get_drawing_mouse_pos()
    idx = _find_node_near(pos)
    if idx >= 0:
        _selected_idx = idx
    else:
        _selected_idx = -1
    redraw_recoil_canvas()
    _update_selected_ui()


def callback_global_mouse_move(sender, app_data):
    if (not _overlay_drag["name"] and dpg.does_item_exist("ui_overlay_layout")
            and dpg.is_mouse_button_down(1) and dpg.is_item_hovered("ui_overlay_layout")):
        callback_overlay_layout_press(sender, app_data)
    callback_overlay_layout_drag(sender, app_data)
    if not _drag["active"]:
        return
    if not dpg.is_mouse_button_down(0):
        _drag.update(active=False, idx=-1, last=None)
        return
    curr = dpg.get_mouse_pos(local=False)
    last = _drag["last"]
    if last is None:
        _drag["last"] = curr
        return
    scale = _drag.get("scale", 1.0)
    if scale < 0.001:
        _drag["last"] = curr
        return
    dx = (curr[0] - last[0]) / scale
    dy = (curr[1] - last[1]) / scale
    if abs(dx) > 0.001 or abs(dy) > 0.001:
        idx = _drag["idx"]
        nodes = DEFAULT_STATE["recoil_nodes"]
        if 0 <= idx < len(nodes):
            nodes[idx][1] += dx
            nodes[idx][2] += dy
            redraw_recoil_canvas()
            _update_selected_ui()
    _drag["last"] = curr


def callback_global_mouse_release(sender, app_data):
    _drag.update(active=False, idx=-1, last=None)


def callback_clear_nodes(sender, app_data):
    global _selected_idx
    _selected_idx = -1
    DEFAULT_STATE["recoil_nodes"] = [[0.0, 0.0, 0.0]]
    redraw_recoil_canvas()
    _update_node_info()
    _update_selected_ui()


def callback_toggle_overlay(sender, app_data):
    redraw_recoil_canvas()


def redraw_recoil_canvas():
    if not dpg.does_item_exist("recoil_canvas"):
        return
    dpg.delete_item("recoil_canvas", children_only=True)
    w, h = CANVAS_W, CANVAS_H

    if dpg.does_item_exist("ui_overlay_combo"):
        if dpg.get_value("ui_overlay_combo") == "Load recoil_bg.png" \
                and dpg.does_item_exist("texture_recoil_background"):
            dpg.draw_image("texture_recoil_background", (0, 0), (w, h),
                           parent="recoil_canvas")

    grid_step = 40
    for gx in range(0, w + 1, grid_step):
        dpg.draw_line((gx, 0), (gx, h), color=(18, 18, 24, 255),
                      thickness=1, parent="recoil_canvas")
    for gy in range(0, h + 1, grid_step):
        dpg.draw_line((0, gy), (w, gy), color=(18, 18, 24, 255),
                      thickness=1, parent="recoil_canvas")

    pts, scale, origin = _compute_canvas_layout()

    ox, oy = origin
    dpg.draw_line((ox, 0), (ox, h), color=(40, 40, 56, 255),
                  thickness=1, parent="recoil_canvas")
    dpg.draw_line((0, oy), (w, oy), color=(40, 40, 56, 255),
                  thickness=1, parent="recoil_canvas")
    dpg.draw_circle((ox, oy), 4, color=(60, 60, 80, 255),
                    fill=(60, 60, 80, 255), parent="recoil_canvas")
    dpg.draw_text((ox + 6, oy - 14), "origin", size=11,
                  color=(55, 55, 70), parent="recoil_canvas")

    nodes = DEFAULT_STATE["recoil_nodes"]
    if not pts:
        dpg.draw_text((w // 2 - 80, h // 2 - 6),
                      "Click to place nodes", size=14,
                      color=(50, 50, 65), parent="recoil_canvas")
        return

    for i in range(len(pts) - 1):
        dpg.draw_line(pts[i], pts[i + 1], color=(110, 40, 200, 255),
                      thickness=2, parent="recoil_canvas")

    for i, (px, py) in enumerate(pts):
        if i == 0:
            col = (0, 200, 120, 255)
        elif i == len(pts) - 1:
            col = (240, 70, 70, 255)
        else:
            col = (0, 170, 235, 255)
        dpg.draw_circle((px, py), 5, color=col, fill=col,
                        parent="recoil_canvas")
        # Selection ring
        if i == _selected_idx:
            dpg.draw_circle((px, py), 10, color=(255, 220, 40, 255),
                            thickness=2, parent="recoil_canvas")
        label_every = max(1, len(pts) // 20)
        if i % label_every == 0 or i == len(pts) - 1 or i == 0 or i == _selected_idx:
            n = nodes[i]
            lbl = f"#{i+1} ({n[1]:+.2f}, {n[2]:+.2f})"
            lx_off = 8 if (i % 2 == 0) else -len(lbl) * 6
            dpg.draw_text((px + lx_off, py - 14), lbl, size=11,
                          color=(160, 160, 175), parent="recoil_canvas")

    dpg.draw_text((w - 120, h - 16), f"zoom: {scale:.0f} px/unit",
                  size=11, color=(50, 50, 65), parent="recoil_canvas")


# ---------------------------------------------------------------------------
# PATTERN IMPORT (.txt — Lew29 / mgsweet format)
# works for taking screenshots and converting them to cords
# use Recoil_processor/run_extractor.py for patterns
# ---------------------------------------------------------------------------
def callback_import_pattern_btn(sender, app_data):
    dpg.show_item("import_file_dialog")

def callback_import_file_ok(sender, app_data):
    selections = app_data.get("selections", {})
    if not selections:
        return
    filepath = list(selections.values())[0]
    try:
        raw_nodes = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cleaned = line.replace('. ', ', ')
                parts = [p.strip() for p in cleaned.split(',')]
                if len(parts) >= 2:
                    x, y = float(parts[0]), float(parts[1])
                    raw_nodes.append((x, y))
        if not raw_nodes:
            logging.warning("Import: no valid nodes found")
            return
        iv = dpg.get_value("ui_time_interval")
        recoil_nodes = [[round(i * iv, 4), x, y] for i, (x, y) in enumerate(raw_nodes)]
        DEFAULT_STATE["recoil_nodes"] = recoil_nodes
        redraw_recoil_canvas()
        _update_node_info()
        logging.info(f"Imported {len(raw_nodes)} nodes from {os.path.basename(filepath)}")
    except Exception as e:
        logging.error(f"Import failed: {e}")

def callback_import_file_cancel(sender, app_data):
    pass


def redraw_burst_canvas():
    if not dpg.does_item_exist("burst_canvas"): return
    count = dpg.get_value("ui_burst_count")
    yp    = dpg.get_value("ui_burst_pull")
    xp    = dpg.get_value("ui_burst_x")
    if None in (count, yp, xp): return
    dpg.delete_item("burst_canvas", children_only=True)
    w, h = 580, 160
    for i in range(1, 6):
        dpg.draw_line(((w/6)*i, 0), ((w/6)*i, h), color=(35, 35, 42, 255), parent="burst_canvas")
    pts = []; cx, cy = w // 2, 20
    for _ in range(min(count, 15)):
        pts.append((cx, cy))
        cx = max(5, min(w-5, cx + int(xp * 1.5)))
        cy = max(5, min(h-5, cy + int(yp * 1.5)))
    for i in range(len(pts) - 1):
        dpg.draw_line(pts[i], pts[i+1], color=(0, 191, 255, 255), thickness=2, parent="burst_canvas")
        dpg.draw_circle(pts[i], 4, color=(147, 51, 234, 255), fill=(147, 51, 234, 255), parent="burst_canvas")
    if pts:
        dpg.draw_circle(pts[-1], 4, color=(147, 51, 234, 255), fill=(147, 51, 234, 255), parent="burst_canvas")


def ui_thread_push_sync(sender, app_data, user_data):
    try: DATA_QUEUE.put_nowait({user_data: app_data})
    except queue.Full: pass
    if user_data in ["recoil_module_enabled", "burst_module_enabled"]:
        with STATE_LOCK:
            DEFAULT_STATE[user_data] = app_data
        send_overlay_state()
    if user_data in ["burst_count", "burst_y_pull", "burst_x_pull"]:
        redraw_burst_canvas()
    if user_data == "time_step_interval":
        _recalc_node_times()

# ---------------------------------------------------------------------------
# FULLSCREEN OVERLAY
# ---------------------------------------------------------------------------
def current_overlay_state():
    """Return the small runtime-state subset consumed by the renderer."""
    with STATE_LOCK:
        return {
            "recoil_enabled": bool(DEFAULT_STATE["recoil_module_enabled"]),
            "burst_enabled": bool(DEFAULT_STATE["burst_module_enabled"]),
            "distance_2x": bool(DEFAULT_STATE["distance_scale_2x_active"]),
        }

def send_overlay_state():
    queue_overlay_update("state", current_overlay_state())

def queue_overlay_update(kind, payload):
    """Queue an overlay update or retain its latest value for the next frame."""
    if not (OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive() and OVERLAY_COMMAND_QUEUE):
        return False
    try:
        OVERLAY_COMMAND_QUEUE.put_nowait((kind, payload))
        OVERLAY_PENDING_UPDATES.pop(kind, None)
        return True
    except queue.Full:
        OVERLAY_PENDING_UPDATES[kind] = payload
        return False

def flush_overlay_updates():
    """Deliver coalesced updates without blocking DearPyGui's render loop."""
    if not (OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive() and OVERLAY_COMMAND_QUEUE):
        OVERLAY_PENDING_UPDATES.clear()
        return
    for kind, payload in list(OVERLAY_PENDING_UPDATES.items()):
        try:
            OVERLAY_COMMAND_QUEUE.put_nowait((kind, payload))
        except queue.Full:
            break
        else:
            OVERLAY_PENDING_UPDATES.pop(kind, None)

def start_overlay():
    """Start the isolated renderer using current validated settings."""
    global OVERLAY_PROCESS, OVERLAY_COMMAND_QUEUE, OVERLAY_STATUS_QUEUE
    if OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive():
        send_overlay_state()
        return
    context = multiprocessing.get_context("spawn")
    OVERLAY_COMMAND_QUEUE = context.Queue(maxsize=16)
    OVERLAY_STATUS_QUEUE = context.Queue(maxsize=16)
    OVERLAY_PROCESS = context.Process(
        target=run_overlay,
        args=(OVERLAY_COMMAND_QUEUE, OVERLAY_STATUS_QUEUE, OVERLAY_CONFIG, current_overlay_state()),
        name="overlay-renderer",
        daemon=True,
    )
    OVERLAY_PROCESS.start()
    _set_overlay_enabled_ui(True)
    _update_overlay_process_ui("STARTING", (255, 190, 60))

def stop_overlay():
    """Request renderer shutdown and terminate only if it cannot exit promptly."""
    global OVERLAY_PROCESS, OVERLAY_COMMAND_QUEUE, OVERLAY_STATUS_QUEUE
    OVERLAY_PENDING_UPDATES.clear()
    process = OVERLAY_PROCESS
    if not process:
        _set_overlay_enabled_ui(False)
        return
    if process.is_alive() and OVERLAY_COMMAND_QUEUE:
        try:
            OVERLAY_COMMAND_QUEUE.put_nowait(("stop",))
        except queue.Full:
            pass
        process.join(timeout=1.5)
    if process.is_alive():
        logging.warning("Overlay renderer did not stop cleanly; terminating it")
        process.terminate()
        process.join(timeout=1.0)
    OVERLAY_PROCESS = None
    OVERLAY_COMMAND_QUEUE = None
    OVERLAY_STATUS_QUEUE = None
    _set_overlay_enabled_ui(False)
    _update_overlay_process_ui("STOPPED", (140, 140, 150))

def restart_overlay():
    stop_overlay()
    start_overlay()

def callback_overlay_start(sender, app_data):
    start_overlay()

def callback_overlay_stop(sender, app_data):
    stop_overlay()

def callback_overlay_restart(sender, app_data):
    restart_overlay()

def callback_overlay_enabled(sender, app_data):
    """Start or stop the overlay from the GUI's primary toggle."""
    if app_data:
        start_overlay()
    else:
        stop_overlay()

def _set_overlay_enabled_ui(enabled):
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if does_item_exist and does_item_exist("ui_overlay_enabled"):
        dpg.set_value("ui_overlay_enabled", bool(enabled))

def _update_overlay_process_ui(text, color):
    if dpg.does_item_exist("ui_overlay_status"):
        dpg.set_value("ui_overlay_status", text)
        dpg.configure_item("ui_overlay_status", color=color)

def poll_overlay_status():
    """Drain renderer lifecycle messages on DearPyGui's main thread."""
    if not OVERLAY_STATUS_QUEUE:
        return
    while True:
        try:
            message = OVERLAY_STATUS_QUEUE.get_nowait()
        except queue.Empty:
            break
        status = message[0]
        if status in ("badge_moved", "badge_move_finished"):
            _, name, x, y = message
            badge = OVERLAY_CONFIG["badges"][name]
            badge["x"], badge["y"] = x, y
            dpg.set_value(f"ui_overlay_{name}_x", x)
            dpg.set_value(f"ui_overlay_{name}_y", y)
            redraw_overlay_previews()
            if status == "badge_move_finished":
                save_overlay_config(OVERLAY_CONFIG)
                _update_overlay_process_ui("SAVED POSITION", (0, 200, 120))
            continue
        detail = message[1]
        if status == "running":
            _set_overlay_enabled_ui(True)
            _update_overlay_process_ui("RUNNING", (0, 200, 120))
        elif status == "error":
            _set_overlay_enabled_ui(False)
            _update_overlay_process_ui(f"ERROR: {detail}", (239, 68, 68))
        else:
            _set_overlay_enabled_ui(False)
            _update_overlay_process_ui("STOPPED", (140, 140, 150))

def _overlay_config_from_ui():
    background_color = list(dpg.get_value("ui_overlay_background_color"))
    background_color[3] = round(dpg.get_value("ui_overlay_background_opacity") * 255)
    config = {
        "mode": dpg.get_value("ui_fullscreen_overlay_mode"),
        "background_color": background_color,
        "always_on_top": dpg.get_value("ui_overlay_topmost"),
        "click_through": dpg.get_value("ui_overlay_click_through"),
        "toggle_source": dpg.get_value("ui_overlay_toggle_source"),
        "toggle_key": dpg.get_value("ui_overlay_toggle_key"),
        "font_path": dpg.get_value("ui_overlay_font_path"),
        "font_scale": dpg.get_value("ui_overlay_font_scale"),
        "badges": {},
    }
    for name in ("recoil", "burst", "distance"):
        prefix = f"ui_overlay_{name}"
        on_color = list(dpg.get_value(f"{prefix}_on_color"))
        off_color = list(dpg.get_value(f"{prefix}_off_color"))
        alpha = round(dpg.get_value(f"{prefix}_opacity") * 255)
        on_color[3] = alpha
        off_color[3] = alpha
        config["badges"][name] = {
            "enabled": dpg.get_value(f"{prefix}_enabled"),
            "label": dpg.get_value(f"{prefix}_label"),
            "x": dpg.get_value(f"{prefix}_x"),
            "y": dpg.get_value(f"{prefix}_y"),
            "width": dpg.get_value(f"{prefix}_width"),
            "height": dpg.get_value(f"{prefix}_height"),
            "on_color": on_color,
            "off_color": off_color,
        }
    return validate_overlay_config(config)

def callback_overlay_setting_changed(sender, app_data):
    global OVERLAY_CONFIG
    OVERLAY_CONFIG = _overlay_config_from_ui()
    redraw_overlay_previews()
    if OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive() and OVERLAY_COMMAND_QUEUE:
        queue_overlay_update("config", OVERLAY_CONFIG)

def callback_overlay_save(sender, app_data):
    global OVERLAY_CONFIG
    OVERLAY_CONFIG = save_overlay_config(_overlay_config_from_ui())
    _update_overlay_process_ui("SAVED", (0, 200, 120))

def callback_overlay_reset(sender, app_data):
    global OVERLAY_CONFIG
    OVERLAY_CONFIG = validate_overlay_config({})
    apply_overlay_config_to_ui(OVERLAY_CONFIG)
    callback_overlay_setting_changed(None, None)
    if OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive():
        restart_overlay()

def apply_overlay_config_to_ui(config):
    dpg.set_value("ui_fullscreen_overlay_mode", config["mode"])
    dpg.set_value("ui_overlay_background_color", config["background_color"])
    dpg.set_value("ui_overlay_background_opacity", _alpha_to_opacity(config["background_color"][3]))
    dpg.set_value("ui_overlay_topmost", config["always_on_top"])
    dpg.set_value("ui_overlay_click_through", config["click_through"])
    dpg.set_value("ui_overlay_toggle_source", config["toggle_source"])
    dpg.set_value("ui_overlay_toggle_key", config["toggle_key"])
    dpg.set_value("ui_overlay_font_path", config["font_path"])
    dpg.set_value("ui_overlay_font_scale", config["font_scale"])
    for name, badge in config["badges"].items():
        prefix = f"ui_overlay_{name}"
        for field in ("enabled", "label", "x", "y", "width", "height", "on_color", "off_color"):
            dpg.set_value(f"{prefix}_{field}", badge[field])
        dpg.set_value(f"{prefix}_opacity", _alpha_to_opacity(badge["on_color"][3]))
    redraw_overlay_previews()

def _alpha_to_opacity(alpha):
    return round((alpha / 255.0) / 0.05) * 0.05

def snap_overlay_opacity(value):
    """Clamp opacity to the 0.05 increments exposed by the GUI."""
    return max(0.0, min(1.0, round(float(value) / 0.05) * 0.05))

def callback_overlay_opacity(sender, app_data, user_data):
    """Snap badge opacity sliders to explicit 0.05 increments."""
    snapped = snap_overlay_opacity(app_data)
    dpg.set_value(sender, snapped)
    callback_overlay_setting_changed(sender, snapped)

def callback_overlay_palette(sender, app_data, user_data):
    """Apply a named RGB swatch while preserving the current opacity."""
    name, state_name, rgb = user_data
    prefix = f"ui_overlay_{name}_{state_name}"
    opacity = dpg.get_value(f"ui_overlay_{name}_opacity")
    dpg.set_value(f"{prefix}_color", [*rgb, round(opacity * 255)])
    callback_overlay_setting_changed(sender, app_data)

def callback_overlay_background_palette(sender, app_data, user_data):
    color = list(dpg.get_value("ui_overlay_background_color"))
    dpg.set_value("ui_overlay_background_color", [*user_data, color[3]])
    callback_overlay_setting_changed(sender, app_data)

def callback_overlay_background_opacity(sender, app_data):
    snapped = snap_overlay_opacity(app_data)
    dpg.set_value(sender, snapped)
    color = list(dpg.get_value("ui_overlay_background_color"))
    color[3] = round(snapped * 255)
    dpg.set_value("ui_overlay_background_color", color)
    callback_overlay_setting_changed(sender, snapped)

def callback_overlay_toggle_source(sender, app_data):
    dpg.set_value("ui_overlay_toggle_source", app_data)
    if app_data == "Local keyboard / pedal":
        dpg.show_item("ui_overlay_toggle_key")
    else:
        dpg.hide_item("ui_overlay_toggle_key")
    callback_overlay_setting_changed(sender, app_data)

def callback_overlay_font_selected(sender, app_data):
    selections = app_data.get("selections", {})
    if selections:
        dpg.set_value("ui_overlay_font_path", list(selections.values())[0])
        callback_overlay_setting_changed(sender, app_data)
        if OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive():
            restart_overlay()

def callback_overlay_font_browse(sender, app_data):
    dpg.show_item("overlay_font_dialog")

def redraw_overlay_layout():
    """Draw a scaled primary-screen layout for direct badge placement."""
    if not dpg.does_item_exist("ui_overlay_layout"):
        return
    dpg.delete_item("ui_overlay_layout", children_only=True)
    config = _overlay_config_from_ui()
    screen_w = max(1, ctypes.windll.user32.GetSystemMetrics(0))
    screen_h = max(1, ctypes.windll.user32.GetSystemMetrics(1))
    sx, sy = OVERLAY_LAYOUT_W / screen_w, OVERLAY_LAYOUT_H / screen_h
    dpg.draw_rectangle((0, 0), (OVERLAY_LAYOUT_W, OVERLAY_LAYOUT_H),
                       color=(65, 65, 80, 255), fill=(6, 6, 9, 255),
                       parent="ui_overlay_layout")
    for name, badge in config["badges"].items():
        if not badge["enabled"]:
            continue
        x, y = badge["x"] * sx, badge["y"] * sy
        w, h = max(12, badge["width"] * sx), max(8, badge["height"] * sy)
        color = badge["on_color"]
        dpg.draw_rectangle((x, y), (x + w, y + h), color=color, fill=color,
                           rounding=2, parent="ui_overlay_layout")
        dpg.draw_text((x + 3, y + 2), name.upper(), size=9,
                      color=(255, 255, 255, 255), parent="ui_overlay_layout")

def callback_overlay_layout_press(sender, app_data):
    _overlay_drag.update(name=None, last=dpg.get_mouse_pos(local=False))
    mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
    item_x, item_y = dpg.get_item_rect_min("ui_overlay_layout")
    mx, my = mouse_x - item_x, mouse_y - item_y
    config = _overlay_config_from_ui()
    screen_w = max(1, ctypes.windll.user32.GetSystemMetrics(0))
    screen_h = max(1, ctypes.windll.user32.GetSystemMetrics(1))
    sx, sy = OVERLAY_LAYOUT_W / screen_w, OVERLAY_LAYOUT_H / screen_h
    for name in reversed(("recoil", "burst", "distance")):
        badge = config["badges"][name]
        x, y = badge["x"] * sx, badge["y"] * sy
        w, h = max(12, badge["width"] * sx), max(8, badge["height"] * sy)
        if badge["enabled"] and x <= mx <= x + w and y <= my <= y + h:
            _overlay_drag["name"] = name
            break

def callback_overlay_layout_drag(sender, app_data):
    name = _overlay_drag["name"]
    if not name or not dpg.is_mouse_button_down(1):
        return
    current = dpg.get_mouse_pos(local=False)
    last = _overlay_drag["last"]
    screen_w = max(1, ctypes.windll.user32.GetSystemMetrics(0))
    screen_h = max(1, ctypes.windll.user32.GetSystemMetrics(1))
    dx = round((current[0] - last[0]) * screen_w / OVERLAY_LAYOUT_W)
    dy = round((current[1] - last[1]) * screen_h / OVERLAY_LAYOUT_H)
    prefix = f"ui_overlay_{name}"
    dpg.set_value(f"{prefix}_x", max(0, dpg.get_value(f"{prefix}_x") + dx))
    dpg.set_value(f"{prefix}_y", max(0, dpg.get_value(f"{prefix}_y") + dy))
    _overlay_drag["last"] = current
    callback_overlay_setting_changed(sender, app_data)

def callback_overlay_layout_release(sender, app_data):
    _overlay_drag.update(name=None, last=None)

def callback_overlay_size_preset(sender, app_data, user_data):
    name, width, height = user_data
    prefix = f"ui_overlay_{name}"
    dpg.set_value(f"{prefix}_width", width)
    dpg.set_value(f"{prefix}_height", height)
    callback_overlay_setting_changed(sender, app_data)

def redraw_overlay_previews():
    """Render the three configured badges inside their vertical GUI sections."""
    if not dpg.does_item_exist("ui_overlay_recoil_preview"):
        return
    config = _overlay_config_from_ui()
    state = current_overlay_state()
    for name, badge in config["badges"].items():
        parent = f"ui_overlay_{name}_preview"
        dpg.delete_item(parent, children_only=True)
        active = state[f"{name}_enabled"] if name != "distance" else state["distance_2x"]
        color = badge["on_color"] if active else badge["off_color"]
        label = badge["label"]
        if name == "distance":
            label += " 2X" if active else " 1X"
        preview_width = min(300, badge["width"])
        preview_height = min(65, badge["height"])
        dpg.draw_rectangle((5, 5), (5 + preview_width, 5 + preview_height),
                           color=color, fill=color, rounding=5, parent=parent)
        dpg.draw_text((14, 12), label, color=(255, 255, 255, color[3]),
                      size=max(10, min(24, int(preview_height * 0.36))), parent=parent)
    redraw_overlay_layout()

# ---------------------------------------------------------------------------
# DEVICE UI CALLBACKS
# ---------------------------------------------------------------------------
def callback_device_type_changed(sender, app_data):
    t = app_data if app_data else dpg.get_value("ui_device_type")
    dpg.show_item("grp_kmbox") if t == "KMBox" else dpg.hide_item("grp_kmbox")
    dpg.show_item("grp_makcu") if t == "Makcu" else dpg.hide_item("grp_makcu")

def callback_device_connect(sender, app_data):
    global _last_device_connect_time
    now = time.monotonic()
    if now - _last_device_connect_time < DEVICE_CONNECT_COOLDOWN:
        return
    if not DEVICE_CONNECT_LOCK.acquire(blocking=False):
        return
    _last_device_connect_time = now
    if dpg.does_item_exist("ui_device_connect"):
        dpg.configure_item("ui_device_connect", enabled=False)
    cfg = {
        "device_type":   dpg.get_value("ui_device_type"),
        "kmbox_ip":      dpg.get_value("ui_kmbox_ip"),
        "kmbox_port":    dpg.get_value("ui_kmbox_port"),
        "kmbox_id":      dpg.get_value("ui_kmbox_id"),
        "kmbox_monitor": dpg.get_value("ui_kmbox_monitor"),
        "makcu_com":     dpg.get_value("ui_makcu_com"),
        "makcu_baud":    dpg.get_value("ui_makcu_baud"),
    }
    try:
        success = connect_device_from_config(cfg)
        save_device_config(cfg)
        _update_device_status_ui(success)
    finally:
        DEVICE_CONNECT_LOCK.release()
        if dpg.does_item_exist("ui_device_connect"):
            dpg.configure_item("ui_device_connect", enabled=True)

def callback_refresh_com_ports(sender, app_data):
    ports = get_available_com_ports()
    dpg.configure_item("ui_makcu_com", items=ports)
    if ports: dpg.set_value("ui_makcu_com", ports[0])

def _update_device_status_ui(connected: bool, message=None):
    is_kmbox = isinstance(DEVICE, KMBoxDevice)
    txt = "READY / UNVERIFIED" if connected and is_kmbox else ("CONNECTED" if connected else "OFFLINE")
    col = (255, 190, 60) if connected and is_kmbox else (
        (0, 255, 120) if connected else (239, 68, 68)
    )
    dpg.set_value("ui_device_status", txt)
    dpg.configure_item("ui_device_status", color=col)
    if connected and is_kmbox:
        sidebar = f"  {DEVICE.name()} READY"
    else:
        sidebar = f"  {DEVICE.name()}" if connected else f"  {DEVICE.name()} OFFLINE"
    dpg.set_value("ui_device_sidebar", sidebar)
    sidebar_color = (255, 190, 60) if connected and is_kmbox else (
        (0, 191, 255) if connected else (140, 140, 150)
    )
    dpg.configure_item("ui_device_sidebar", color=sidebar_color)
    if dpg.does_item_exist("ui_device_error"):
        dpg.set_value("ui_device_error", "" if connected else (message or "Device unavailable"))

def _update_distance_scale_ui(scale_2x_active):
    """Keep distance status synchronized with runtime and manual changes."""
    if dpg.does_item_exist("ui_distance_scale_status"):
        far_x = dpg.get_value("ui_far_scale_x") if dpg.does_item_exist("ui_far_scale_x") else 2.0
        far_y = dpg.get_value("ui_far_scale_y") if dpg.does_item_exist("ui_far_scale_y") else 2.0
        label = f"FAR — X {far_x:.2f} / Y {far_y:.2f}" if scale_2x_active else "BASE — X 1.00 / Y 1.00"
        color = (255, 190, 60) if scale_2x_active else (0, 200, 120)
        dpg.set_value("ui_distance_scale_status", label)
        dpg.configure_item("ui_distance_scale_status", color=color)
    if dpg.does_item_exist("ui_distance_scale_manual"):
        dpg.set_value("ui_distance_scale_manual", scale_2x_active)
    send_overlay_state()
    redraw_overlay_previews()

def callback_distance_scale_enabled(sender, app_data):
    ui_thread_push_sync(sender, app_data, "distance_scale_enabled")

def callback_distance_scale_source(sender, app_data):
    source = app_data or "Local keyboard / pedal"
    ui_thread_push_sync(sender, source, "distance_scale_source")
    if dpg.does_item_exist("ui_distance_scale_local_group"):
        if source == "Local keyboard / pedal":
            dpg.show_item("ui_distance_scale_local_group")
        else:
            dpg.hide_item("ui_distance_scale_local_group")

def callback_distance_scale_manual(sender, app_data):
    active = bool(app_data)
    with STATE_LOCK:
        DEFAULT_STATE["distance_scale_2x_active"] = active
    ui_thread_push_sync(sender, active, "distance_scale_2x_active")
    _update_distance_scale_ui(active)

def callback_far_scale(sender, app_data, user_data):
    """Update a Far axis, optionally mirroring it to the linked axis."""
    value = snap_far_scale(app_data)
    dpg.set_value(sender, value)
    other_key = "far_scale_y" if user_data == "far_scale_x" else "far_scale_x"
    ui_thread_push_sync(sender, value, user_data)
    if dpg.get_value("ui_far_scale_linked"):
        dpg.set_value(f"ui_{other_key}", value)
        ui_thread_push_sync(sender, value, other_key)
    with STATE_LOCK:
        active = DEFAULT_STATE["distance_scale_2x_active"]
    _update_distance_scale_ui(active)

def callback_far_scale_linked(sender, app_data):
    ui_thread_push_sync(sender, bool(app_data), "far_scale_linked")
    if app_data:
        value = snap_far_scale(dpg.get_value("ui_far_scale_x"))
        dpg.set_value("ui_far_scale_y", value)
        ui_thread_push_sync(sender, value, "far_scale_y")
    with STATE_LOCK:
        active = DEFAULT_STATE["distance_scale_2x_active"]
    _update_distance_scale_ui(active)

def callback_hw_ks_toggle(sender, app_data):
    with STATE_LOCK: DEFAULT_STATE["hw_killswitch_enabled"] = app_data

def callback_hw_ks_key(sender, app_data):
    with STATE_LOCK: DEFAULT_STATE["hw_killswitch_key"] = app_data

# ---------------------------------------------------------------------------
# MISC UI CALLBACKS
# ---------------------------------------------------------------------------
_TAB_INFO = {
    "panel_recoil":   ("btn_tab_recoil",   "Recoil Workspace"),
    "panel_burst":    ("btn_tab_burst",    "Burst Mode (93R)"),
    "panel_settings": ("btn_tab_settings", "Settings Panel"),
    "panel_overlay":  ("btn_tab_overlay",  "Overlay")
}

def ui_tab_navigation(sender, app_data, user_data):
    # Hide all, show selected
    for t in _TAB_INFO:
        dpg.hide_item(t)
    dpg.show_item(user_data)

    # Dynamic styling and text shifting (animation)
    for panel, (btn_tag, base_label) in _TAB_INFO.items():
        if dpg.does_item_exist(btn_tag):
            if panel == user_data:
                # Active tab: Bright purple text, subtle background
                dpg.bind_item_theme(btn_tag, "theme_tab_active")
                dpg.configure_item(btn_tag, label=f"   {base_label} ")
            else:
                # Inactive tab: Muted gray text, standard background
                dpg.bind_item_theme(btn_tag, "theme_tab_inactive")
                dpg.configure_item(btn_tag, label=f"   {base_label} ")

def callback_viewport_resize(sender, app_data):
    if dpg.does_item_exist("shell"):
        dpg.configure_item("shell", width=app_data[0]-15, height=app_data[1]-35)

def add_overlay_badge_section(name, title, badge):
    """Build one vertically separated badge editor and live preview."""
    prefix = f"ui_overlay_{name}"
    with dpg.child_window(height=255, border=True):
        with dpg.group(horizontal=True):
            with dpg.group(width=245):
                with dpg.group(horizontal=True):
                    dpg.add_text(title.upper(), color=(190, 120, 255))
                    dpg.add_checkbox(label="Show on overlay", default_value=badge["enabled"],
                                     tag=f"{prefix}_enabled",
                                     callback=callback_overlay_setting_changed)
                dpg.add_drawlist(width=235, height=88, tag=f"{prefix}_preview")
                dpg.add_input_text(label="Label", default_value=badge["label"], width=125,
                                   tag=f"{prefix}_label", callback=callback_overlay_setting_changed)
            dpg.add_spacer(width=8)
            with dpg.group():
                dpg.add_text("Placement", color=(140, 140, 150))
                with dpg.group(horizontal=True):
                    dpg.add_input_int(label="X", default_value=badge["x"], width=65,
                                      min_value=0, min_clamped=True, tag=f"{prefix}_x",
                                      callback=callback_overlay_setting_changed)
                    dpg.add_input_int(label="Y", default_value=badge["y"], width=65,
                                      min_value=0, min_clamped=True, tag=f"{prefix}_y",
                                      callback=callback_overlay_setting_changed)
                dpg.add_text("Size", color=(140, 140, 150))
                with dpg.group(horizontal=True):
                    dpg.add_input_int(label="Width", default_value=badge["width"], width=65,
                                      min_value=30, min_clamped=True, tag=f"{prefix}_width",
                                      callback=callback_overlay_setting_changed)
                    dpg.add_input_int(label="Height", default_value=badge["height"], width=65,
                                      min_value=16, min_clamped=True, tag=f"{prefix}_height",
                                      callback=callback_overlay_setting_changed)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Small", width=55, callback=callback_overlay_size_preset,
                                   user_data=(name, 100, 30))
                    dpg.add_button(label="Medium", width=60, callback=callback_overlay_size_preset,
                                   user_data=(name, 150, 42))
                    dpg.add_button(label="Large", width=55, callback=callback_overlay_size_preset,
                                   user_data=(name, 220, 60))

        dpg.add_separator()
        dpg.add_slider_float(
            label="Transparency (0 invisible / 1 solid)",
            default_value=_alpha_to_opacity(badge["on_color"][3]),
            min_value=0.0, max_value=1.0, format="%.2f", width=240,
            tag=f"{prefix}_opacity", callback=callback_overlay_opacity,
        )
        state_labels = (("on", "2x"), ("off", "1x")) if name == "distance" \
            else (("on", "Enabled"), ("off", "Disabled"))
        for state_name, label in state_labels:
            with dpg.group(horizontal=True):
                dpg.add_text(f"{label}:", color=(140, 140, 150))
                for palette_name, rgb in OVERLAY_COLOR_PALETTE.items():
                    dpg.add_color_button(
                        [*rgb, 255], width=23, height=18, no_border=True,
                        callback=callback_overlay_palette,
                        user_data=(name, state_name, rgb),
                    )
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(palette_name)

        with dpg.collapsing_header(label="Advanced custom colors", default_open=False):
            with dpg.group(horizontal=True):
                on_label = "2x custom" if name == "distance" else "Enabled custom"
                off_label = "1x custom" if name == "distance" else "Disabled custom"
                dpg.add_color_picker(
                    label=on_label, default_value=badge["on_color"], width=230,
                    no_alpha=True, display_rgb=True, display_hex=True,
                    tag=f"{prefix}_on_color", callback=callback_overlay_setting_changed,
                )
                dpg.add_color_picker(
                    label=off_label, default_value=badge["off_color"], width=230,
                    no_alpha=True, display_rgb=True, display_hex=True,
                    tag=f"{prefix}_off_color", callback=callback_overlay_setting_changed,
                )

# ---------------------------------------------------------------------------
# RUNTIME LIFECYCLE
# ---------------------------------------------------------------------------
WORKER_JOIN_TIMEOUT = 1.0

def start_runtime_workers(stop_event):
    """Start background workers and return handles for orderly shutdown."""
    workers = []
    if sys.platform.startswith('win'):
        workers.append(threading.Thread(
            target=_apply_dark_titlebar_worker,
            args=(stop_event,),
            name="dark-titlebar",
            daemon=True,
        ))
    workers.extend([
        threading.Thread(
            target=main_pc_keyboard_listener_worker,
            args=(stop_event,),
            name="panic-listener",
            daemon=True,
        ),
        threading.Thread(
            target=hardware_consumer_engine,
            args=(DATA_QUEUE, stop_event),
            name="hardware-engine",
            daemon=True,
        ),
    ])
    for worker in workers:
        worker.start()
    return workers

def shutdown_runtime(stop_event, workers):
    """Stop workers before releasing the active hardware device."""
    stop_event.set()
    stop_overlay()
    for worker in workers:
        worker.join(timeout=WORKER_JOIN_TIMEOUT)
        if worker.is_alive():
            logging.warning(f"Worker did not stop cleanly: {worker.name}")
    try:
        DEVICE.disconnect()
    except Exception as exc:
        logging.error(f"Device disconnect failed: {exc}")

# ---------------------------------------------------------------------------
# UI BUILD
# ---------------------------------------------------------------------------
def build_tactical_surface():
    # Connect device from saved config before building UI
    dev_cfg = load_device_config()
    connect_device_from_config(dev_cfg)

    dpg.create_context()

    if os.path.exists("recoil_bg.png"):
        try:
            w, h, _, data = dpg.load_image("recoil_bg.png")
            with dpg.texture_registry():
                dpg.add_static_texture(width=w, height=h, default_value=data, tag="texture_recoil_background")
        except Exception as e:
            logging.warning(f"overlay image: {e}")

    with dpg.theme() as gtheme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,      (10, 10, 12, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,       (16, 16, 20, 255))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,       (24, 24, 30, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Button,        (130, 40, 210, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (155, 60, 240, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,  4.0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0.0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,    12.0, 10.0)
    dpg.bind_theme(gtheme)

    # ── TAB ANIMATION THEMES ────────────────────────────────────────────
    # for the sidebar ui tabs animation shit
    with dpg.theme(tag="theme_tab_active"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 30, 65, 255))        # Deep purple backdrop
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (65, 45, 90, 255)) 
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (85, 60, 120, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (190, 120, 255, 255))       # Glowing neon text
            
    with dpg.theme(tag="theme_tab_inactive"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (24, 24, 30, 255))        # Flat dark background
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (35, 35, 45, 255)) 
            dpg.add_theme_color(dpg.mvThemeCol_Text, (140, 140, 150, 255))       # Muted gray text

    dpg.create_viewport(title="AimASSist Control Workspace", width=820, height=620, resizable=True)

    with dpg.window(tag="shell", no_title_bar=True, no_scrollbar=True, no_move=True, no_resize=True, no_bring_to_front_on_focus=True):
        with dpg.group(horizontal=True):

            # ── SIDEBAR ─────────────────────────────────────────────────
            with dpg.child_window(tag="sidebar_child", width=160, height=-1, border=False):
                dpg.add_spacer(height=15)
                dpg.add_text("  AimASSist", color=(145, 55, 240))
                dpg.add_spacer(height=20)
                dpg.add_button(tag="btn_tab_recoil",   width=145, height=35, callback=ui_tab_navigation, user_data="panel_recoil")
                dpg.add_button(tag="btn_tab_burst",    width=145, height=35, callback=ui_tab_navigation, user_data="panel_burst")
                dpg.add_button(tag="btn_tab_settings", width=145, height=35, callback=ui_tab_navigation, user_data="panel_settings")
                dpg.add_button(tag="btn_tab_overlay",  width=145, height=35, callback=ui_tab_navigation, user_data="panel_overlay")
                
                dpg.add_spacer(height=100)
                dpg.add_separator()
                dpg.add_text(" Mod links:")
                dpg.add_checkbox(label="Recoil", default_value=True, tag="ui_toggle_recoil_mod",
                                 callback=ui_thread_push_sync, user_data="recoil_module_enabled")
                dpg.add_checkbox(label="Burst",  default_value=True, tag="ui_toggle_burst_mod",
                                 callback=ui_thread_push_sync, user_data="burst_module_enabled")
                dpg.add_spacer(height=20)
                dpg.add_separator()
                dpg.add_text("  Master:")
                dpg.add_text("  ONLINE", tag="ui_status_text", color=(0, 255, 120))
                dpg.add_spacer(height=6)
                dpg.add_text("  Device:")
                _dev_name  = DEVICE.name()
                _dev_color = (0, 191, 255) if DEVICE.is_connected() else (140, 140, 150)
                _dev_label = f"  {_dev_name}" if DEVICE.is_connected() else f"  {_dev_name} OFFLINE"
                dpg.add_text(_dev_label, tag="ui_device_sidebar", color=_dev_color)


            # ── MAIN PANELS ──────────────────────────────────────────────
            with dpg.group():

                # Profile bar
                with dpg.child_window(width=-1, height=50, border=False):
                    with dpg.group(horizontal=True):
                        dpg.add_text(" Profiles:", color=(140, 140, 150))
                        dpg.add_combo(get_config_files(), tag="ui_config_selector", width=160, default_value="Select Profile")
                        dpg.add_button(label="Load", width=70, callback=callback_load_config)
                        dpg.add_spacer(width=6)
                        dpg.add_input_text(hint="name", tag="ui_save_name", width=130)
                        dpg.add_button(label="Save", width=70, callback=callback_save_config)

                # ── RECOIL TAB ──────────────────────────────────────────
                with dpg.child_window(tag="panel_recoil", width=-1, height=-1, border=False):
                    dpg.add_text("Recoil Workspace", color=(145, 55, 240))
                    dpg.add_separator()

                    with dpg.group(horizontal=True):
                        with dpg.group():
                            dpg.add_text("Trigger:", color=(88, 88, 108))
                            dpg.add_combo(["Mouse 5", "Mouse 4", "Left Click"],
                                          default_value="Mouse 5", tag="ui_recoil_trigger_combo",
                                          width=110, callback=ui_thread_push_sync,
                                          user_data="recoil_trigger_key")
                            dpg.add_checkbox(label="Latch mode", tag="ui_recoil_is_toggle",
                                             callback=ui_thread_push_sync,
                                             user_data="recoil_is_toggle")
                        dpg.add_spacer(width=14)
                        with dpg.group():
                            dpg.add_text("KS key:", color=(88, 88, 108))
                            dpg.add_combo(KS_KEY_OPTIONS, default_value="None",
                                          tag="ui_recoil_ks_key", width=110,
                                          callback=ui_thread_push_sync,
                                          user_data="recoil_ks_key")
                            dpg.add_checkbox(label="Require ADS", tag="ui_recoil_req_ads",
                                             callback=ui_thread_push_sync,
                                             user_data="recoil_require_ads")
                        dpg.add_spacer(width=14)
                        with dpg.group():
                            dpg.add_text("Scale:", color=(88, 88, 108))
                            dpg.add_slider_float(label="X", default_value=1.0,
                                                 min_value=0.0, max_value=5.0,
                                                 tag="ui_recoil_scale_x", width=100,
                                                 callback=ui_thread_push_sync,
                                                 user_data="recoil_scale_x")
                            dpg.add_slider_float(label="Y", default_value=1.0,
                                                 min_value=0.0, max_value=5.0,
                                                 tag="ui_recoil_scale_y", width=100,
                                                 callback=ui_thread_push_sync,
                                                 user_data="recoil_scale_y")
                        dpg.add_spacer(width=14)
                        with dpg.group():
                            dpg.add_text("Jitter:", color=(88, 88, 108))
                            dpg.add_slider_float(label="", default_value=0.05,
                                                 min_value=0.0, max_value=2.0,
                                                 tag="ui_recoil_jitter", width=100,
                                                 callback=ui_thread_push_sync,
                                                 user_data="recoil_jitter")

                    dpg.add_spacer(height=4)

                    with dpg.collapsing_header(label="Distance Scaling", default_open=True):
                        with dpg.group(horizontal=True):
                            dpg.add_checkbox(label="Enable toggle input",
                                             tag="ui_distance_scale_enabled",
                                             callback=callback_distance_scale_enabled)
                            dpg.add_combo(DISTANCE_SCALE_SOURCES,
                                          default_value="Local keyboard / pedal",
                                          tag="ui_distance_scale_source", width=155,
                                          callback=callback_distance_scale_source)
                            with dpg.group(tag="ui_distance_scale_local_group"):
                                dpg.add_input_text(default_value="num 1", hint="numpad / pedal key",
                                                   tag="ui_distance_scale_local_key", width=110,
                                                   callback=ui_thread_push_sync,
                                                   user_data="distance_scale_local_key")
                            dpg.hide_item("ui_distance_scale_local_group")
                            dpg.add_checkbox(label="Far mode", tag="ui_distance_scale_manual",
                                             callback=callback_distance_scale_manual)
                        dpg.add_text("BASE — X 1.00 / Y 1.00", tag="ui_distance_scale_status",
                                     color=(0, 200, 120))
                        with dpg.group(horizontal=True):
                            dpg.add_slider_float(label="Far X", default_value=2.0,
                                                 min_value=0.5, max_value=2.5, format="%.2f",
                                                 tag="ui_far_scale_x", width=150,
                                                 callback=callback_far_scale, user_data="far_scale_x")
                            dpg.add_slider_float(label="Far Y", default_value=2.0,
                                                 min_value=0.5, max_value=2.5, format="%.2f",
                                                 tag="ui_far_scale_y", width=150,
                                                 callback=callback_far_scale, user_data="far_scale_y")
                            dpg.add_checkbox(label="Link X/Y", default_value=False,
                                             tag="ui_far_scale_linked",
                                             callback=callback_far_scale_linked)
                        dpg.add_text("Use a toggle input that does not conflict with Fire or a killswitch.",
                                     color=(100, 100, 110))

                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(label="Interval (s)", default_value=0.15,
                                             min_value=0.02, max_value=0.40,
                                             tag="ui_time_interval", width=120,
                                             callback=ui_thread_push_sync,
                                             user_data="time_step_interval")
                        dpg.add_spacer(width=6)
                        dpg.add_button(label="Clear", width=50,
                                       callback=callback_clear_nodes)
                        dpg.add_spacer(width=6)
                        dpg.add_button(label="Import .txt", width=78,
                                       callback=callback_import_pattern_btn)
                        dpg.add_spacer(width=6)
                        dpg.add_combo(["None", "Load recoil_bg.png"],
                                      default_value="None", label="BG",
                                      tag="ui_overlay_combo", width=145,
                                      callback=callback_toggle_overlay)

                    dpg.add_spacer(height=3)
                    dpg.add_text("L-click: add/select  |  Drag: move  |  R-click: select",
                                 color=(42, 42, 58))
                    dpg.add_spacer(height=3)

                    with dpg.child_window(width=606, height=358, border=True):
                        dpg.add_drawlist(width=590, height=340, tag="recoil_canvas")
                        with dpg.item_handler_registry(tag="canvas_handler"):
                            dpg.add_item_clicked_handler(button=0,
                                                         callback=callback_canvas_left_click)
                            dpg.add_item_clicked_handler(button=1,
                                                         callback=callback_canvas_right_click)
                        dpg.bind_item_handler_registry("recoil_canvas", "canvas_handler")

                    # ── Node editor + info row ────────────────────────
                    with dpg.group(horizontal=True):
                        dpg.add_text("Empty — click canvas or import a .txt",
                                     tag="ui_node_count_text", color=(48, 120, 175))

                    dpg.add_spacer(height=4)

                    with dpg.group(horizontal=True):
                        # Selected node editor
                        dpg.add_text("No selection", tag="ui_sel_label", color=(55, 55, 70))
                        dpg.add_spacer(width=10)
                        dpg.add_text("vx:", color=(62, 62, 80))
                        dpg.add_input_float(tag="ui_sel_vx", default_value=0.0, width=75,
                                            step=0.05, callback=callback_edit_sel_vx)
                        dpg.add_spacer(width=6)
                        dpg.add_text("vy:", color=(62, 62, 80))
                        dpg.add_input_float(tag="ui_sel_vy", default_value=0.0, width=75,
                                            step=0.05, callback=callback_edit_sel_vy)
                        dpg.add_spacer(width=10)
                        dpg.add_button(label="Delete node", width=78,
                                       callback=callback_delete_selected)
                        dpg.add_spacer(width=20)
                        # Zoom controls
                        dpg.add_button(label="-", width=24, callback=callback_zoom_out)
                        dpg.add_button(label="Fit", width=32, callback=callback_zoom_fit)
                        dpg.add_button(label="+", width=24, callback=callback_zoom_in)

                # ── BURST TAB ───────────────────────────────────────────
                with dpg.child_window(tag="panel_burst", width=-1, height=-1, border=False):
                    dpg.hide_item("panel_burst")
                    dpg.add_text("Stepped Burst Mechanical Calibration Matrix (93R)", color=(145, 55, 240))
                    dpg.add_separator()

                    with dpg.group(horizontal=True):
                        with dpg.group():
                            dpg.add_text("Trigger Key:", color=(140, 140, 150))
                            dpg.add_combo(["Mouse 5", "Mouse 4", "Left Click"],
                                          default_value="Mouse 4", tag="ui_burst_trigger_combo", width=140,
                                          callback=ui_thread_push_sync, user_data="burst_trigger_key")
                            dpg.add_checkbox(label="Latch Mode — arm once, fire until pressed again",
                                             tag="ui_burst_is_toggle",
                                             callback=ui_thread_push_sync, user_data="burst_is_toggle")
                        dpg.add_spacer(width=30)
                        with dpg.group():
                            dpg.add_text("Module KS Key:", color=(140, 140, 150))
                            dpg.add_combo(KS_KEY_OPTIONS, default_value="None",
                                          tag="ui_burst_ks_key", width=140,
                                          callback=ui_thread_push_sync, user_data="burst_ks_key")
                            dpg.add_text("Press to toggle Burst ON/OFF", color=(100, 100, 110))
                            dpg.add_spacer(height=4)
                            dpg.add_checkbox(label="Require ADS (Right Click) to Fire",
                                             tag="ui_burst_req_ads",
                                             callback=ui_thread_push_sync, user_data="burst_require_ads")

                    dpg.add_spacer(height=10)
                    dpg.add_slider_int(label="Rounds Per Burst Cycle", default_value=3, min_value=2, max_value=5,
                                       tag="ui_burst_count", width=180,
                                       callback=ui_thread_push_sync, user_data="burst_count")
                    dpg.add_slider_float(label="Vertical Pull Drop (Y)", default_value=14.0, min_value=0.0, max_value=40.0,
                                         tag="ui_burst_pull", width=180,
                                         callback=ui_thread_push_sync, user_data="burst_y_pull")
                    dpg.add_slider_float(label="Horizontal Corrections (X)", default_value=0.0, min_value=-10.0, max_value=10.0,
                                         tag="ui_burst_x", width=180,
                                         callback=ui_thread_push_sync, user_data="burst_x_pull")
                    dpg.add_spacer(height=10)
                    dpg.add_text("The Finals Timing Constraints:", color=(145, 55, 240))
                    dpg.add_slider_float(label="Intra-Burst Pacing (ms)  [60.0]",
                                         default_value=60.0, min_value=10.0, max_value=120.0,
                                         tag="ui_burst_intra_ms", width=180,
                                         callback=ui_thread_push_sync, user_data="burst_intra_delay_ms")
                    dpg.add_slider_float(label="Inter-Burst Recovery (ms)  [275.0]",
                                         default_value=275.0, min_value=100.0, max_value=400.0,
                                         tag="ui_burst_inter_ms", width=180,
                                         callback=ui_thread_push_sync, user_data="burst_inter_delay_ms")
                    dpg.add_spacer(height=10)
                    with dpg.group(horizontal=True):
                        with dpg.group():
                            dpg.add_text("Visual Vector Map:", color=(110, 110, 120))
                            dpg.add_text("Stabilizes burst climb.", color=(110, 110, 120))
                        with dpg.child_window(width=350, height=180, border=True):
                            dpg.add_drawlist(width=335, height=160, tag="burst_canvas")

                # ── SETTINGS TAB ────────────────────────────────────────
                with dpg.child_window(tag="panel_settings", width=-1, height=-1, border=False):
                    dpg.hide_item("panel_settings")
                    dpg.add_text("AimASSist Configuration", color=(145, 55, 240))
                    dpg.add_separator()

                    # ── DEVICE CONNECTION ────────────────────────────────
                    dpg.add_spacer(height=10)
                    dpg.add_text("Device Connection", color=(0, 191, 255))

                    with dpg.group(horizontal=True):
                        dpg.add_text("Device type:", color=(140, 140, 150))
                        dpg.add_combo(["KMBox", "Makcu", "Simulation"],
                                      default_value=dev_cfg.get("device_type", "KMBox"),
                                      tag="ui_device_type", width=130,
                                      callback=callback_device_type_changed)

                    dpg.add_spacer(height=6)

                    # KMBox fields
                    with dpg.group(tag="grp_kmbox"):
                        with dpg.group(horizontal=True):
                            dpg.add_text("IP:", color=(140, 140, 150))
                            dpg.add_input_text(default_value=dev_cfg["kmbox_ip"],
                                               tag="ui_kmbox_ip", width=130)
                            dpg.add_text("  Port:", color=(140, 140, 150))
                            dpg.add_input_text(default_value=dev_cfg["kmbox_port"],
                                               tag="ui_kmbox_port", width=70)
                        with dpg.group(horizontal=True):
                            dpg.add_text("Device ID:", color=(140, 140, 150))
                            dpg.add_input_text(default_value=dev_cfg["kmbox_id"],
                                               tag="ui_kmbox_id", width=130)
                            dpg.add_text("  Monitor:", color=(140, 140, 150))
                            dpg.add_input_int(default_value=dev_cfg["kmbox_monitor"],
                                              tag="ui_kmbox_monitor", width=80)

                    # Makcu fields (hidden by default unless config says Makcu)
                    with dpg.group(tag="grp_makcu"):
                        dpg.add_text("Fill in the TODO blocks in MakcuDevice before connecting.",
                                     color=(100, 100, 110))
                        with dpg.group(horizontal=True):
                            dpg.add_text("COM Port:", color=(140, 140, 150))
                            _com_ports = get_available_com_ports()
                            dpg.add_combo(_com_ports,
                                          default_value=dev_cfg.get("makcu_com", _com_ports[0]),
                                          tag="ui_makcu_com", width=120)
                            dpg.add_button(label="↺", width=28, callback=callback_refresh_com_ports)
                            dpg.add_text("  Baud:", color=(140, 140, 150))
                            dpg.add_input_int(default_value=dev_cfg.get("makcu_baud", 115200),
                                              tag="ui_makcu_baud", width=90)

                    # Hide whichever group shouldn't show
                    callback_device_type_changed(None, dev_cfg.get("device_type", "KMBox"))

                    dpg.add_spacer(height=8)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Initialize / Reinitialize", width=180,
                                       tag="ui_device_connect", callback=callback_device_connect)
                        dpg.add_spacer(width=10)
                        _conn_txt = (
                            "READY / UNVERIFIED"
                            if isinstance(DEVICE, KMBoxDevice) and DEVICE.is_connected()
                            else ("CONNECTED" if DEVICE.is_connected() else "OFFLINE")
                        )
                        _conn_col = (
                            (255, 190, 60)
                            if isinstance(DEVICE, KMBoxDevice) and DEVICE.is_connected()
                            else ((0, 255, 120) if DEVICE.is_connected() else (239, 68, 68))
                        )
                        dpg.add_text(_conn_txt, tag="ui_device_status", color=_conn_col)
                    dpg.add_text("KMNet uses UDP; initialization cannot prove the box replied.",
                                 color=(100, 100, 110))
                    dpg.add_text("", tag="ui_device_error", color=(239, 68, 68), wrap=560)

                    dpg.add_spacer(height=15)
                    dpg.add_separator()

                    # ── SENSITIVITY ──────────────────────────────────────
                    dpg.add_spacer(height=10)
                    dpg.add_text("Step 1: Hip-fire sensitivity", color=(0, 191, 255))
                    dpg.add_input_float(label="", default_value=22.0, tag="ui_input_sens",
                                        width=160, callback=ui_thread_push_sync, user_data="local_sens")

                    dpg.add_spacer(height=12)
                    dpg.add_text("Step 2: ADS zoom multiplier", color=(0, 191, 255))
                    dpg.add_text("75% zoom = 0.75", color=(120, 120, 130))
                    dpg.add_input_float(label="", default_value=0.75, tag="ui_input_zoom_mult",
                                        width=160, callback=ui_thread_push_sync, user_data="local_zoom_mult")

                    dpg.add_spacer(height=12)
                    dpg.add_text("Step 3: FOV", color=(0, 191, 255))
                    dpg.add_input_int(label="", default_value=100, tag="ui_input_fov",
                                      width=160, callback=ui_thread_push_sync, user_data="local_fov")

                    dpg.add_spacer(height=12)
                    dpg.add_text("Step 4: Local Panic Button  (keyboard key)", color=(239, 68, 68))
                    dpg.add_combo(["/", "F4", "Insert", "Home"], default_value="/",
                                  tag="ui_toggle_combo", label="", width=160,
                                  callback=callback_update_hotkey)

                    dpg.add_spacer(height=16)
                    dpg.add_separator()
                    dpg.add_spacer(height=8)
                    dpg.add_text("Step 5: Global Hardware Killswitch  (optional)", color=(239, 68, 68))
                    dpg.add_text("Per-tab KS Keys are the main way — this is a backup.", color=(100, 100, 110))
                    dpg.add_checkbox(label="Enable", default_value=False,
                                     tag="ui_hw_ks_enabled", callback=callback_hw_ks_toggle)
                    dpg.add_combo(KS_KEY_OPTIONS[1:], default_value="Mouse 5",
                                  tag="ui_hw_ks_key_combo", width=160, callback=callback_hw_ks_key)

                # ── OVERLAY TAB ─────────────────────────────────────────
                with dpg.child_window(tag="panel_overlay", width=-1, height=-1, border=False):
                    dpg.hide_item("panel_overlay")
                    dpg.add_text("Fullscreen Display Overlay", color=(145, 55, 240))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(label="Overlay enabled", default_value=False,
                                         tag="ui_overlay_enabled",
                                         callback=callback_overlay_enabled)
                        dpg.add_button(label="Start", width=75, callback=callback_overlay_start)
                        dpg.add_button(label="Stop", width=75, callback=callback_overlay_stop)
                        dpg.add_button(label="Restart", width=75, callback=callback_overlay_restart)
                        dpg.add_button(label="Save", width=75, callback=callback_overlay_save)
                        dpg.add_button(label="Reset", width=75, callback=callback_overlay_reset)
                        dpg.add_text("STOPPED", tag="ui_overlay_status", color=(140, 140, 150))
                    with dpg.child_window(height=210, border=True):
                        dpg.add_text("DISPLAY", color=(190, 120, 255))
                        with dpg.group(horizontal=True):
                            dpg.add_combo(["Display Fuser", "Transparent"],
                                          default_value=OVERLAY_CONFIG["mode"], label="Mode", width=135,
                                          tag="ui_fullscreen_overlay_mode",
                                          callback=callback_overlay_setting_changed)
                            dpg.add_checkbox(label="Always on top", default_value=OVERLAY_CONFIG["always_on_top"],
                                             tag="ui_overlay_topmost", callback=callback_overlay_setting_changed)
                            dpg.add_checkbox(label="Click through", default_value=OVERLAY_CONFIG["click_through"],
                                             tag="ui_overlay_click_through", callback=callback_overlay_setting_changed)
                        dpg.add_text("Background palette", color=(140, 140, 150))
                        with dpg.group(horizontal=True):
                            for palette_name, rgb in OVERLAY_COLOR_PALETTE.items():
                                dpg.add_color_button([*rgb, 255], width=28, height=20, no_border=True,
                                                     callback=callback_overlay_background_palette,
                                                     user_data=rgb)
                                with dpg.tooltip(dpg.last_item()):
                                    dpg.add_text(palette_name)
                            dpg.add_color_edit(label="Custom", default_value=OVERLAY_CONFIG["background_color"],
                                               width=110, no_alpha=True, tag="ui_overlay_background_color",
                                               callback=callback_overlay_setting_changed)
                        dpg.add_slider_float(label="Background opacity", min_value=0.0, max_value=1.0,
                                             default_value=_alpha_to_opacity(OVERLAY_CONFIG["background_color"][3]),
                                             format="%.2f", width=220,
                                             tag="ui_overlay_background_opacity",
                                             callback=callback_overlay_background_opacity)
                        with dpg.group(horizontal=True):
                            dpg.add_combo(OVERLAY_TOGGLE_SOURCES,
                                          default_value=OVERLAY_CONFIG["toggle_source"],
                                          label="Toggle source", width=160,
                                          tag="ui_overlay_toggle_source",
                                          callback=callback_overlay_toggle_source)
                            dpg.add_input_text(label="Key / pedal", default_value=OVERLAY_CONFIG["toggle_key"],
                                               width=70, tag="ui_overlay_toggle_key",
                                               callback=callback_overlay_setting_changed)
                            dpg.add_input_text(label="Font file", default_value=OVERLAY_CONFIG["font_path"],
                                               width=190, readonly=True, tag="ui_overlay_font_path")
                            dpg.add_button(label="Browse", callback=callback_overlay_font_browse)
                            dpg.add_slider_float(label="Font scale", default_value=OVERLAY_CONFIG["font_scale"],
                                                 min_value=0.5, max_value=3.0, width=90,
                                                 tag="ui_overlay_font_scale",
                                                 callback=callback_overlay_setting_changed)
                    dpg.add_text("Right-drag a badge in this scaled screen preview to place it.",
                                 color=(100, 100, 110))
                    dpg.add_drawlist(width=OVERLAY_LAYOUT_W, height=OVERLAY_LAYOUT_H,
                                     tag="ui_overlay_layout")
                    dpg.add_spacer(height=5)
                    add_overlay_badge_section("recoil", "Recoil", OVERLAY_CONFIG["badges"]["recoil"])
                    add_overlay_badge_section("burst", "Burst", OVERLAY_CONFIG["badges"]["burst"])
                    add_overlay_badge_section("distance", "Distance", OVERLAY_CONFIG["badges"]["distance"])

    # -- GLOBAL MOUSE HANDLERS for canvas drag
    with dpg.handler_registry():
        dpg.add_mouse_move_handler(callback=callback_global_mouse_move)
        dpg.add_mouse_release_handler(button=0, callback=callback_global_mouse_release)
        dpg.add_mouse_release_handler(button=1, callback=callback_overlay_layout_release)


    # File dialog for .txt pattern import
    with dpg.file_dialog(directory_selector=False, show=False,
                         callback=callback_import_file_ok,
                         cancel_callback=callback_import_file_cancel,
                         tag="import_file_dialog", width=500, height=400):
        dpg.add_file_extension(".txt", color=(0, 200, 120, 255))
        dpg.add_file_extension(".*")

    with dpg.file_dialog(directory_selector=False, show=False,
                         callback=callback_overlay_font_selected,
                         tag="overlay_font_dialog", width=520, height=420):
        dpg.add_file_extension(".ttf", color=(0, 200, 120, 255))
        dpg.add_file_extension(".otf", color=(0, 170, 235, 255))

    dpg.setup_dearpygui()
    dpg.show_viewport()

    # ADD THIS LINE HERE TO ENGAGE THE PRIMARY WINDOW ENGINE:
    dpg.set_primary_window("shell", True)

    stop_event = threading.Event()
    workers = start_runtime_workers(stop_event)

    try:
        redraw_recoil_canvas()
        _update_node_info()
        redraw_burst_canvas()
        redraw_overlay_previews()

        # Apply the initial tab styling now that everything is built
        ui_tab_navigation(None, None, "panel_recoil")

        while dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
            # Drain deferred UI updates — all DPG writes from background threads land here
            while True:
                try:
                    msg = UI_UPDATE_QUEUE.get_nowait()
                    if msg[0] == "set_value":
                        dpg.set_value(msg[1], msg[2])
                    elif msg[0] == "status":
                        ok = msg[1]
                        dpg.set_value("ui_status_text", "ONLINE" if ok else "PAUSED")
                        dpg.configure_item("ui_status_text", color=(0, 255, 120) if ok else (239, 68, 68))
                    elif msg[0] == "device_status":
                        _update_device_status_ui(msg[1], msg[2])
                    elif msg[0] == "distance_scale":
                        _update_distance_scale_ui(msg[1])
                    elif msg[0] == "runtime_state":
                        send_overlay_state()
                        redraw_overlay_previews()
                    elif msg[0] == "overlay_toggle":
                        if OVERLAY_PROCESS and OVERLAY_PROCESS.is_alive():
                            stop_overlay()
                        else:
                            start_overlay()
                except queue.Empty:
                    break
            poll_overlay_status()
            flush_overlay_updates()
    finally:
        shutdown_runtime(stop_event, workers)
        dpg.destroy_context()


if __name__ == "__main__":
    build_tactical_surface()