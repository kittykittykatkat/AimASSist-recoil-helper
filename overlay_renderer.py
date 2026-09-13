"""Isolated DearPyGui renderer for the fullscreen display-fuser overlay."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from pathlib import Path
from ctypes import wintypes

from overlay_config import validate_overlay_config


WINDOW_TITLE = "AimASSist Status Overlay"
TRANSPARENT_KEY = [1, 0, 1, 255]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _screen_size() -> tuple[int, int]:
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except OSError:
            pass
        return (
            ctypes.windll.user32.GetSystemMetrics(0),
            ctypes.windll.user32.GetSystemMetrics(1),
        )
    return 1920, 1080


def _colorref(color: list[int]) -> int:
    return color[0] | (color[1] << 8) | (color[2] << 16)


def _apply_window_styles(config: dict) -> None:
    """Apply Windows styles unavailable through DearPyGui's viewport API."""
    if not sys.platform.startswith("win"):
        return
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return
    gwl_exstyle = -20
    ws_ex_layered = 0x00080000
    ws_ex_transparent = 0x00000020
    ws_ex_noactivate = 0x08000000
    style = user32.GetWindowLongW(hwnd, gwl_exstyle)
    style |= ws_ex_layered | ws_ex_noactivate
    if config["click_through"]:
        style |= ws_ex_transparent
    else:
        style &= ~ws_ex_transparent
    user32.SetWindowLongW(hwnd, gwl_exstyle, style)
    user32.SetLayeredWindowAttributes(hwnd, _colorref(TRANSPARENT_KEY), 255, 0x1)
    insert_after = -1 if config["always_on_top"] else -2
    user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, 0x0013)


def _badge_color(name: str, badge: dict, state: dict) -> list[int]:
    active = state.get(f"{name}_enabled", False)
    if name == "distance":
        active = state.get("distance_2x", False)
    return badge["on_color"] if active else badge["off_color"]


def _badge_at(config: dict, x: int, y: int) -> str | None:
    """Return the topmost visible badge under a screen coordinate."""
    for name in reversed(tuple(config["badges"])):
        badge = config["badges"][name]
        if not badge["enabled"]:
            continue
        if (badge["x"] <= x <= badge["x"] + badge["width"]
                and badge["y"] <= y <= badge["y"] + badge["height"]):
            return name
    return None


def _clamp_badge_position(badge: dict, x: int, y: int, screen_width: int,
                          screen_height: int) -> tuple[int, int]:
    """Keep a dragged badge fully visible on the primary display."""
    return (
        max(0, min(screen_width - badge["width"], int(x))),
        max(0, min(screen_height - badge["height"], int(y))),
    )


def _right_mouse_state() -> tuple[bool, int, int]:
    """Read global right-button and cursor state despite click-through styles."""
    if not sys.platform.startswith("win"):
        return False, 0, 0
    point = _Point()
    user32 = ctypes.windll.user32
    user32.GetCursorPos(ctypes.byref(point))
    pressed = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
    return pressed, point.x, point.y


def _background_opacity(config: dict) -> float:
    """Convert the saved background alpha channel to window opacity."""
    return max(0.0, min(1.0, config["background_color"][3] / 255.0))


def _run_background_window(config_queue, stop_event, initial_config: dict,
                           ready_event) -> None:
    """Render an independently translucent native layer behind the badges."""
    if not sys.platform.startswith("win"):
        stop_event.wait()
        return
    config = validate_overlay_config(initial_config)
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32
    lresult = ctypes.c_ssize_t
    wparam = ctypes.c_size_t
    lparam = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wparam, lparam]
    user32.DefWindowProcW.restype = lresult
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    class_name = "AimASSistOverlayBackgroundClass"
    wndproc_type = ctypes.WINFUNCTYPE(
        lresult, wintypes.HWND, wintypes.UINT, wparam, lparam
    )

    @wndproc_type
    def window_proc(hwnd, message, wparam, lparam):
        if message == 0x0010:  # WM_CLOSE
            user32.DestroyWindow(hwnd)
            return 0
        if message == 0x0002:  # WM_DESTROY
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    class WndClassEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_type), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
        ]

    instance = kernel32.GetModuleHandleW(None)
    window_class = WndClassEx()
    window_class.cbSize = ctypes.sizeof(WndClassEx)
    window_class.lpfnWndProc = window_proc
    window_class.hInstance = instance
    window_class.lpszClassName = class_name
    user32.RegisterClassExW(ctypes.byref(window_class))
    ex_style = 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080
    hwnd = user32.CreateWindowExW(
        ex_style, class_name, f"{WINDOW_TITLE} Background", 0x80000000,
        0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1),
        None, None, instance, None,
    )
    if not hwnd:
        raise OSError(f"Background window creation failed: {ctypes.get_last_error()}")

    def apply_config() -> None:
        color = config["background_color"]
        rect = wintypes.RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        dc = user32.GetDC(hwnd)
        brush = gdi32.CreateSolidBrush(_colorref(color))
        user32.FillRect(dc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        user32.ReleaseDC(hwnd, dc)
        alpha = round(_background_opacity(config) * 255)
        user32.SetLayeredWindowAttributes(hwnd, 0, alpha, 0x2)
        insert_after = -1 if config["always_on_top"] else -2
        user32.SetWindowPos(hwnd, insert_after, 0, 0, rect.right, rect.bottom, 0x0010)
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE

    apply_config()
    ready_event.set()
    message = wintypes.MSG()
    while not stop_event.is_set():
        while True:
            try:
                next_config, applied_event = config_queue.get_nowait()
            except queue.Empty:
                break
            config = validate_overlay_config(next_config)
            apply_config()
            applied_event.set()
        while user32.PeekMessageW(ctypes.byref(message), hwnd, 0, 0, 0x0001):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        stop_event.wait(0.016)
    user32.DestroyWindow(hwnd)
    user32.UnregisterClassW(class_name, instance)


def run_overlay(command_queue, status_queue, initial_config: dict, initial_state: dict) -> None:
    """Run the renderer until the parent sends a stop command or closes the queue."""
    import dearpygui.dearpygui as dpg

    config = validate_overlay_config(initial_config)
    state = dict(initial_state)
    width, height = _screen_size()
    clear_color = TRANSPARENT_KEY
    failed = False
    background_queue = queue.Queue(maxsize=4)
    background_stop = threading.Event()
    background_ready = threading.Event()
    background_thread = threading.Thread(
        target=_run_background_window,
        args=(background_queue, background_stop, config, background_ready),
        name="overlay-background",
        daemon=True,
    )
    try:
        background_thread.start()
        if not background_ready.wait(timeout=1.0):
            raise RuntimeError("Overlay background did not initialize")
        dpg.create_context()
        font_path = Path(config["font_path"]) if config.get("font_path") else None
        if font_path and font_path.is_file() and font_path.suffix.lower() in (".ttf", ".otf"):
            with dpg.font_registry():
                overlay_font = dpg.add_font(str(font_path), 32)
            dpg.bind_font(overlay_font)
        dpg.create_viewport(
            title=WINDOW_TITLE,
            width=width,
            height=height,
            x_pos=0,
            y_pos=0,
            decorated=False,
            resizable=False,
            always_on_top=config["always_on_top"],
            clear_color=clear_color,
            vsync=True,
        )
        with dpg.theme() as surface_theme:
            with dpg.theme_component(dpg.mvWindowAppItem):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, TRANSPARENT_KEY)
                dpg.add_theme_color(dpg.mvThemeCol_Border, TRANSPARENT_KEY)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
        with dpg.window(
            tag="overlay_surface",
            no_title_bar=True,
            no_move=True,
            no_resize=True,
            no_scrollbar=True,
            width=width,
            height=height,
            pos=(0, 0),
        ):
            dpg.add_drawlist(tag="overlay_drawlist", width=width, height=height)
        dpg.bind_item_theme("overlay_surface", surface_theme)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("overlay_surface", True)
        _apply_window_styles(config)
        status_queue.put_nowait(("running", "Overlay running"))

        redraw = True
        dragged_badge = None
        drag_offset = (0, 0)
        while dpg.is_dearpygui_running():
            while True:
                try:
                    message = command_queue.get_nowait()
                except queue.Empty:
                    break
                kind = message[0]
                if kind == "stop":
                    return
                if kind == "state":
                    state.update(message[1])
                    redraw = True
                elif kind == "config":
                    config = validate_overlay_config(message[1])
                    try:
                        while True:
                            background_queue.get_nowait()
                    except queue.Empty:
                        pass
                    background_applied = threading.Event()
                    try:
                        background_queue.put_nowait((config, background_applied))
                    except queue.Full:
                        pass
                    background_applied.wait(timeout=0.1)
                    _apply_window_styles(config)
                    redraw = True

            right_down, cursor_x, cursor_y = _right_mouse_state()
            if right_down and dragged_badge is None:
                dragged_badge = _badge_at(config, cursor_x, cursor_y)
                if dragged_badge:
                    badge = config["badges"][dragged_badge]
                    drag_offset = (cursor_x - badge["x"], cursor_y - badge["y"])
            elif right_down and dragged_badge:
                badge = config["badges"][dragged_badge]
                new_x, new_y = _clamp_badge_position(
                    badge,
                    cursor_x - drag_offset[0],
                    cursor_y - drag_offset[1],
                    width,
                    height,
                )
                if (new_x, new_y) != (badge["x"], badge["y"]):
                    badge["x"], badge["y"] = new_x, new_y
                    redraw = True
                    try:
                        status_queue.put_nowait(("badge_moved", dragged_badge, new_x, new_y))
                    except queue.Full:
                        pass
            elif not right_down and dragged_badge:
                badge = config["badges"][dragged_badge]
                try:
                    status_queue.put(
                        ("badge_move_finished", dragged_badge, badge["x"], badge["y"]),
                        timeout=0.1,
                    )
                except queue.Full:
                    pass
                dragged_badge = None
            if redraw:
                dpg.delete_item("overlay_drawlist", children_only=True)
                dpg.set_viewport_clear_color(TRANSPARENT_KEY)
                for name, badge in config["badges"].items():
                    if not badge["enabled"]:
                        continue
                    x, y = badge["x"], badge["y"]
                    color = _badge_color(name, badge, state)
                    label = badge["label"]
                    if name == "distance":
                        label = f"{label} {'2X' if state.get('distance_2x') else '1X'}"
                    dpg.draw_rectangle(
                        (x, y),
                        (x + badge["width"], y + badge["height"]),
                        color=color,
                        fill=color,
                        rounding=5,
                        parent="overlay_drawlist",
                    )
                    text_size = max(10, int(badge["height"] * 0.36 * config["font_scale"]))
                    dpg.draw_text(
                        (x + 10, y + max(2, (badge["height"] - text_size) // 2)),
                        label,
                        color=(255, 255, 255, color[3]),
                        size=text_size,
                        parent="overlay_drawlist",
                    )
                redraw = False
            dpg.render_dearpygui_frame()
    except Exception as exc:
        failed = True
        try:
            status_queue.put_nowait(("error", str(exc)))
        except queue.Full:
            pass
    finally:
        background_stop.set()
        if background_thread.is_alive():
            background_thread.join(timeout=1.0)
        try:
            dpg.destroy_context()
        except Exception:
            pass
        if not failed:
            try:
                status_queue.put_nowait(("stopped", "Overlay stopped"))
            except queue.Full:
                pass