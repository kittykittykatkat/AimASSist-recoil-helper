"""
run_extractor.py — Fullscreen recoil pattern builder (MAIN VERSION)
=========================================================
Opens FULLSCREEN. No title bar, no wasted space. Your screenshot fills
the entire monitor. Click each hole, export, done.

Controls:
    Left-click      Place node on bullet hole
    Scroll wheel    Zoom in/out at cursor
    Middle-drag     Pan around when zoomed
    +/= or -        Zoom in/out
    Arrow keys      Pan
    F               Fit (reset zoom)
    Z               Undo last click
    C               Clear all
    Q / ENTER       Export
    ESC             Quit without saving
"""

import cv2, numpy as np, os, glob, sys, math

INPUT_DIR, OUTPUT_DIR = "./inputs", "./outputs"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

WEAPONS = {"M11":60,"P90":70,"XP54":68,"93R":64,"AKM":99,"FCAR":111,"FAMAS":52,"M60":100,"Lewis":114,"SH1900":200,"Pike":130,"LH1":270,"ARN220":83}

def get_latest():
    f = []
    for e in ("*.png","*.jpg","*.jpeg"): f.extend(glob.glob(os.path.join(INPUT_DIR, e)))
    return max(f, key=os.path.getmtime) if f else None


def paired_midpoints(clicks):
    """Center actual simultaneous impacts without assuming fixed pair spacing."""
    if len(clicks) % 2:
        raise ValueError("Complete the final impact pair before export")
    return [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            for a, b in zip(clicks[::2], clicks[1::2])]


def export_pattern(path, clicks, interval_ms, scalar, origin=None):
    """Keep the existing wall-scalar conversion; optionally export paired shots."""
    if not math.isfinite(interval_ms) or interval_ms <= 0:
        raise ValueError("Shot interval must be positive and finite")
    if not math.isfinite(scalar) or scalar <= 0:
        raise ValueError("Wall scalar must be positive and finite")
    points = [origin] + paired_midpoints(clicks) if origin is not None else clicks
    if len(points) < 2:
        raise ValueError("Mark at least two normal nodes or an origin and one pair")
    with open(path, "w") as handle:
        if origin is not None:
            handle.write(f"# interval_ms={interval_ms}\n")
        handle.write("0.00, 0.00\n")
        for first, second in zip(points, points[1:]):
            vx = -(second[0] - first[0]) * scalar / interval_ms
            vy = -(second[1] - first[1]) * scalar / interval_ms
            handle.write(f"{round(vx, 5)}, {round(vy, 5)}\n")
    return len(points)

class Viewport:
    """Fullscreen zoom/pan viewport for any image size."""
    def __init__(self, img_w, img_h, screen_w, screen_h, panel_h=34):
        self.iw, self.ih = img_w, img_h
        self.sw, self.sh = screen_w, screen_h
        self.panel_h = panel_h
        self.view_h = screen_h - panel_h
        self.zoom = 1.0
        self.cx, self.cy = img_w / 2, img_h / 2
        self.panning = False
        self.pan_start = None

    def fit(self):
        self.zoom = min(self.sw / self.iw, self.view_h / self.ih)
        self.cx, self.cy = self.iw / 2, self.ih / 2

    def zoom_in(self, f=1.25): self.zoom = min(self.zoom * f, 20.0)
    def zoom_out(self, f=1.25): self.zoom = max(self.zoom / f, 0.1); self._clamp()

    def zoom_at(self, sx, sy, zin=True):
        ix, iy = self.s2i(sx, sy)
        self.zoom = min(self.zoom * 1.2, 20.0) if zin else max(self.zoom / 1.2, 0.1)
        self.cx, self.cy = ix, iy
        self._clamp()

    def pan(self, dx_s, dy_s):
        self.cx -= dx_s / self.zoom
        self.cy -= dy_s / self.zoom
        self._clamp()

    def pan_key(self, dx, dy):
        speed = 60 / self.zoom
        self.cx += dx * speed
        self.cy += dy * speed
        self._clamp()

    def _clamp(self):
        hw = (self.sw / self.zoom) / 2
        hh = (self.view_h / self.zoom) / 2
        self.cx = max(hw, min(self.iw - hw, self.cx))
        self.cy = max(hh, min(self.ih - hh, self.cy))

    def s2i(self, sx, sy):
        off_x = self.cx - (self.sw / self.zoom) / 2
        off_y = self.cy - (self.view_h / self.zoom) / 2
        return off_x + sx / self.zoom, off_y + sy / self.zoom

    def i2s(self, ix, iy):
        off_x = self.cx - (self.sw / self.zoom) / 2
        off_y = self.cy - (self.view_h / self.zoom) / 2
        return int((ix - off_x) * self.zoom), int((iy - off_y) * self.zoom)

    def render(self, img):
        half_w = (self.sw / self.zoom) / 2
        half_h = (self.view_h / self.zoom) / 2
        src_x1 = max(0, int(self.cx - half_w))
        src_y1 = max(0, int(self.cy - half_h))
        src_x2 = min(self.iw, int(self.cx + half_w))
        src_y2 = min(self.ih, int(self.cy + half_h))

        crop = img[src_y1:src_y2, src_x1:src_x2]
        if crop.size == 0:
            return np.zeros((self.view_h, self.sw, 3), dtype=np.uint8)

        dst_w = int((src_x2 - src_x1) * self.zoom)
        dst_h = int((src_y2 - src_y1) * self.zoom)
        if dst_w < 1 or dst_h < 1:
            return np.zeros((self.view_h, self.sw, 3), dtype=np.uint8)

        scaled = cv2.resize(crop, (dst_w, dst_h), interpolation=
                            cv2.INTER_NEAREST if self.zoom > 3 else cv2.INTER_LINEAR)

        canvas = np.zeros((self.view_h, self.sw, 3), dtype=np.uint8)
        ox = max(0, (self.sw - dst_w) // 2)
        oy = max(0, (self.view_h - dst_h) // 2)
        paste_w = min(dst_w, self.sw - ox)
        paste_h = min(dst_h, self.view_h - oy)
        canvas[oy:oy+paste_h, ox:ox+paste_w] = scaled[:paste_h, :paste_w]

        return canvas


def draw_markers(frame, clicks, vp):
    for i, (ix, iy) in enumerate(clicks):
        sx, sy = vp.i2s(ix, iy)
        if not (0 <= sx < vp.sw and 0 <= sy < vp.view_h):
            continue
        if i == 0:
            cv2.circle(frame, (sx, sy), 6, (255, 0, 255), -1)
            cv2.circle(frame, (sx, sy), 10, (255, 0, 255), 1)
            cv2.putText(frame, "1", (sx+12, sy+5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,0,255), 1, cv2.LINE_AA)
        else:
            px, py = vp.i2s(*clicks[i-1])
            cv2.line(frame, (px, py), (sx, sy), (0, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(frame, (sx, sy), 4, (0, 0, 255), -1)
            side = 8 if i % 2 == 0 else -16
            cv2.putText(frame, str(i+1), (sx+side, sy+4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,255,0), 1, cv2.LINE_AA)

    if vp.zoom > 1.2:
        cx, cy = vp.sw // 2, vp.view_h // 2
        cv2.line(frame, (cx-12,cy), (cx+12,cy), (50,50,50), 1)
        cv2.line(frame, (cx,cy-12), (cx,cy+12), (50,50,50), 1)


def draw_panel(sw, panel_h, clicks, weapon, ims, zoom, status="", scalar=4.5):
    panel = np.zeros((panel_h, sw, 3), dtype=np.uint8)
    panel[:] = (18, 18, 22)
    cv2.line(panel, (0, 0), (sw, 0), (40, 40, 50), 1)

    left = f"  {len(clicks)} nodes | {weapon} {ims}ms | Zoom {zoom:.1f}x | Scalar: {scalar}"
    cv2.putText(panel, left, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170,170,180), 1)

    right = "Scroll=zoom  Mid-drag=pan  Z=undo  C=clear  Q=export  ESC=quit"
    cv2.putText(panel, right, (sw-550, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80,80,90), 1)

    if status:
        cv2.putText(panel, status, (sw//2-40, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,200,120), 1)

    return panel


def get_user_settings():
    """Interactive CLI menu for weapon and scale selection."""
    print("\n" + "="*40)
    print(" AIMASSIST PROFILE EXTRACTOR")
    print("="*40)
    print("\nAvailable Weapons:")

    w_keys = list(WEAPONS.keys()) + ["SHAK"]
    for i, w in enumerate(w_keys):
        timing = f"{WEAPONS[w]}ms" if w in WEAPONS else "paired impacts; measured interval"
        print(f"  [{i+1}] {w:<8} ({timing})")

    print("")

    sel = input("Select a weapon number or name (Default: AKM): ").strip()
    selected_weapon = None

    if sel.isdigit() and 1 <= int(sel) <= len(w_keys):
        selected_weapon = w_keys[int(sel)-1]
    else:
        for w in w_keys:
            if sel.lower() == w.lower():
                selected_weapon = w
                break

    if not selected_weapon:
        print("[*] Defaulting to AKM.")
        selected_weapon = "AKM"

    scalar_in = input("Enter wall scalar (Press ENTER for default 4.5): ").strip()
    try:
        scalar = float(scalar_in) if scalar_in else 4.5
    except ValueError:
        scalar = 4.5

    if not math.isfinite(scalar) or scalar <= 0:
        raise ValueError("Wall scalar must be positive and finite")
    if selected_weapon == "SHAK":
        while True:
            try:
                interval = float(input("Milliseconds between SHAK trigger pulls (required): ").strip())
                if math.isfinite(interval) and interval > 0:
                    break
            except ValueError:
                pass
            print("[!] Enter a positive, finite interval in milliseconds.")
    else:
        interval = WEAPONS[selected_weapon]
    return selected_weapon, interval, scalar


def run():
    target_weapon, ims, scalar = get_user_settings()

    path = get_latest()
    if not path:
        print(f"\n[!] Error: No images found in {INPUT_DIR}/"); return

    nm = os.path.basename(path)
    img = cv2.imread(path)
    if img is None:
        print(f"\n[!] Error: Can't read {nm}"); return

    ih, iw = img.shape[:2]

    print(f"\n[Profile Architect] Loaded: {nm} ({iw}x{ih})")
    print(f"--> Target Weapon : {target_weapon} ({ims}ms)")
    print(f"--> Wall Scalar   : {scalar}")

    win = "AimASSist Profile Architect"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    screen_w = cv2.getWindowImageRect(win)[2]
    screen_h = cv2.getWindowImageRect(win)[3]
    if screen_w < 100 or screen_h < 100:
        screen_w, screen_h = 1920, 1080

    panel_h = 34
    vp = Viewport(iw, ih, screen_w, screen_h, panel_h)
    vp.fit()

    clicks = []
    origin = None
    shak = target_weapon == "SHAK"
    status = ""

    def refresh():
        frame = vp.render(img)
        markers = ([origin] if origin is not None else []) + paired_midpoints(clicks[:len(clicks)//2*2]) if shak else clicks
        draw_markers(frame, markers, vp)
        display_status = status
        if shak:
            display_status = "Click ORIGIN" if origin is None else f"Pair {len(clicks)//2+1}: impact {len(clicks)%2+1}/2"
            if origin is not None:
                cv2.drawMarker(frame, vp.i2s(*origin), (255, 0, 255), cv2.MARKER_CROSS, 18, 2)
            for i in range(0, len(clicks), 2):
                first = vp.i2s(*clicks[i])
                cv2.circle(frame, first, 4, (255, 180, 0), 1)
                if i + 1 < len(clicks):
                    second = vp.i2s(*clicks[i+1])
                    cv2.circle(frame, second, 4, (255, 180, 0), 1)
                    cv2.line(frame, first, second, (255, 180, 0), 1)
                    width = abs(clicks[i+1][0] - clicks[i][0])
                    cv2.putText(frame, f"Pair {i//2+1}: {width:.1f}px", first,
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 180, 0), 1)
        panel = draw_panel(screen_w, panel_h, markers, target_weapon, ims, vp.zoom, display_status, scalar)
        full = np.vstack([frame, panel])
        cv2.imshow(win, full)

    def on_mouse(event, x, y, flags, param):
        nonlocal status, origin

        if event == cv2.EVENT_LBUTTONDOWN and y < vp.view_h:
            ix, iy = vp.s2i(x, y)
            if 0 <= ix < iw and 0 <= iy < ih:
                if shak and origin is None:
                    origin = (ix, iy)
                else:
                    clicks.append((ix, iy))
                status = f"#{len(clicks)}"
                refresh()

        elif event == cv2.EVENT_MOUSEWHEEL:
            vp.zoom_at(x, y, flags > 0)
            refresh()

        elif event == cv2.EVENT_MBUTTONDOWN:
            vp.panning = True
            vp.pan_start = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and vp.panning:
            if vp.pan_start:
                dx = x - vp.pan_start[0]
                dy = y - vp.pan_start[1]
                vp.pan(dx, dy)
                vp.pan_start = (x, y)
                refresh()

        elif event == cv2.EVENT_MBUTTONUP:
            vp.panning = False
            vp.pan_start = None

    cv2.setMouseCallback(win, on_mouse)
    refresh()

    print("\n  Ready — click each bullet hole first-to-last")
    print("  Press 'Q' or 'ENTER' when finished.")

    while True:
        k = cv2.waitKey(30) & 0xFF
        if k == ord('q') or k == 13:
            if shak and (origin is None or not clicks or len(clicks) % 2):
                print("[!] Mark an origin and complete every pair; Z undoes the last impact.")
                continue
            break
        elif k == 27: cv2.destroyAllWindows(); print("\n[Cancelled]"); return
        elif k == ord('c'): clicks.clear(); origin = None; status = "Cleared"
        elif k == ord('z') and clicks: clicks.pop(); status = f"Undo->{len(clicks)}"
        elif k == ord('z') and shak: origin = None
        elif k == ord('f'): vp.fit(); status = "Fit"
        elif k in (ord('+'), ord('=')): vp.zoom_in()
        elif k == ord('-'): vp.zoom_out()
        elif k in (81, 2): vp.pan_key(-1, 0)
        elif k in (83, 3): vp.pan_key(1, 0)
        elif k in (82, 0): vp.pan_key(0, -1)
        elif k in (84, 1): vp.pan_key(0, 1)
        else: continue
        refresh()
        status = ""

    cv2.destroyAllWindows()

    if len(clicks) < 2:
        print("\n[!] Error: Need 2+ clicks to build a profile."); return

    # ── Export ──
    out = os.path.join(OUTPUT_DIR, os.path.splitext(nm)[0] + f"_{target_weapon}_profile.txt")
    count = export_pattern(out, clicks, ims, scalar, origin if shak else None)

    print(f"\n[Success] Generated {count} tracking nodes.")
    print(f"--> Saved to: {out}")
    print(f"--> Load into Master Control with Scale (X/Y) set to 1.0.")

if __name__ == "__main__":
    run()
