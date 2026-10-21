# AimASSist Control Workspace

Windows/DearPyGui application for editable movement profiles, Linear corrections, Burst compensation and a fullscreen status overlay. KMBox Net output runs from a secondary/control PC. Simulation generates no hardware output.

Originally calibrated for **THE FINALS**. CS2, WARDOGS and generic game setups are planned, not implemented calibration presets. Current engines provide movement, not memory reading, target detection or automatic firing. Hardware use does not guarantee undetectability or compliance with game rules.

## Installation

The bundled `kmNet.cp311-win_amd64.pyd` requires **Windows, 64-bit Python 3.11**. From the repository root:

```powershell
python -m pip install -r requirements.txt
python master_control.py
```

| Backend | Status |
| --- | --- |
| KMBox Net | Native integration; use the actual box IP, port, ID and monitor port |
| Simulation | No hardware output; local input for development |
| Makcu | Unfinished placeholder, not a working supported backend |

KMBox B compatibility is not established. Do not substitute native binaries without checking API and Python ABI compatibility.

## First run

1. Use Simulation to check the GUI without hardware.
2. For KMBox Net, enter device settings and choose **Connect**. Runtime connection requests run on the hardware worker.
3. Load a weapon profile or import a pattern.
4. Match sensitivity, ADS multiplier and FOV to the calibration used for that profile.
5. Configure trigger, ADS requirement and killswitch; avoid conflicting button assignments.
6. Check Master state before expecting output. Changing tabs does not disable modules.

Device settings live in `device.json`; profiles live in `configs`. Keep real device IDs out of shared commits and screenshots.

## Master and keyboard scope

The local Master hotkey defaults to `/`; Settings also offers F4, Insert and Home. It toggles active/paused, not application exit.

**Local keyboard and keyboard-emulating pedal inputs are read on the control PC.** Main-PC keys are not visible unless explicitly routed there. KMBox sources depend on inputs monitored through the box. Local overlay F8 has the same control-PC restriction.

## Movement workspaces

### Pattern recoil

Use **Recoil Workspace** to import or edit timed X/Y nodes. Add/select/drag/delete nodes, adjust interval and base scales, and configure trigger, ADS requirement and latch behavior. Existing Pattern math is retained; scheduler-independent timing is not guaranteed.

### Linear

Open **Linear Workspace**, below Recoil Workspace. **Linear** also appears beneath Recoil in **Mod links**; both checkboxes are synchronized.

Pattern and Linear are mutually exclusive: enabling Linear switches away from Pattern; enabling Recoil selects Pattern. Navigation alone does not switch engines. Older profiles default to Pattern.

| Behavior | X/Y meaning |
| --- | --- |
| Single correction | Total movement once per activation |
| Smooth correction | Total movement distributed over a duration |
| Continuous pull | Movement per second while active |
| Repeat while held | One correction per repeat interval |

Start delay and retrigger cooldown are configurable. Duration/repeat fields appear only for the relevant behavior. Ctrl+click sliders for exact entry. Negative X is left, positive X right; negative Y is up, positive Y down.

Linear shares Recoil trigger, ADS requirement, killswitch, sensitivity and base/Far scaling. Smooth correction stops on release. With latch enabled, activation follows the latched state, not physical release. Editing settings cancels Linear until release. Engine switches/recovery require release/repress when held. Missed repeats are skipped; continuous catch-up is capped at 50 ms. No clicks are generated.

### Burst

Timed groups of X/Y movement corrections with count, intra-group interval and recovery interval. Burst does not fire automatically. Recoil takes priority if both module triggers activate together.

### Distance Scaling / Far mode

Expand **Distance Scaling** in Recoil Workspace. Far X/Y are independent `0.50–2.50` multipliers in `0.05` steps; Link X/Y changes both together. Base uses 1.00. Switch manually or with a configured local keyboard/pedal or KMBox Mouse 4/5 input.

These are **scale presets, not distance detection**. Multiplying by two does not universally convert 25 m calibration to 50 m. Older profiles default to Far 2.00/2.00, unlinked; profile load resets active Far to Base. The overlay retains legacy 1X/2X labels rather than displaying custom Far values.

## Current fullscreen extractor

From the repository root:

```powershell
python -m pip install -r requirements-tools.txt
Set-Location recoil_processor
python run_extractor.py
```

The tool uses `inputs`/`outputs` relative to its **working directory**. Put screenshots in `recoil_processor/inputs`; the newest PNG/JPG/JPEG is selected. Choose weapon and wall scalar in the console before fullscreen opens.

Left-click marks; wheel zooms; middle-drag/arrows pan; F fits; Z undoes; C clears; Q/Enter exports; Escape cancels. Normal extraction retains its wall-scalar conversion and plain-text output. Use **Import .txt** in Master Control and set the matching interval for normal files.

Rendering, marker placement and clicks use the same image transform. Wheel zoom preserves the image point under the cursor except where image-edge bounds require clamping; letterboxed images remain centered while panning.

### Optional SHAK mode

Choose **SHAK** in the same menu and enter measured milliseconds **between trigger pulls**, not between simultaneous projectiles. No rate is assumed.

1. Click the original aim point as the separate origin.
2. Click both impacts from the first trigger pull.
3. Continue pairs in firing order.
4. Review pair lines, widths and midpoint trajectory before exporting.

Each pair uses its actual X/Y midpoint, regardless of separation. Midpoint correction cannot remove projectile spread. Use one capture distance. If 20 rounds are consumed two per trigger, a magazine gives 10 pairs.

Z removes individual impacts, then origin; C resets all. An origin plus one complete pair is the minimum. Incomplete pairs block export. SHAK output contains a leading zero, first midpoint displacement from origin and interval metadata applied automatically on import. Older text files retain the current interval field.

`profile_architect OLD.py` is a legacy reference, not the current tool.

## Fullscreen overlay

The **Overlay** tab is below Settings. Start/Stop/Restart and an enable checkbox control an isolated fullscreen renderer on the primary display.

- Borderless with black default background for display-fuser setups.
- Background color/opacity independent of badge color/opacity.
- Recoil, Burst and Distance badge visibility, colors, labels, size and placement.
- Right-drag directly on fullscreen or use the scaled preview; fullscreen drag placements save automatically.
- Optional TTF/OTF font, topmost and click-through settings.
- Save writes `overlay.json`; running state is not saved.
- Local F8/pedal and optional KMBox Mouse 4/5 toggle sources.

Windows transparency and fuser color-key behavior are different mechanisms. Physical fuser appearance needs hardware validation.

## KMBox health and recovery

**READY / UNVERIFIED** means native initialization returned successfully, not proven delivery or current reachability. A worker heartbeat measures local activity only; no verified network heartbeat is enabled.

On detected movement/input exceptions:

1. Master pauses and runtime cancellation clears pending sequences/leftovers.
2. Reconnect is attempted up to five times with 1/2/4/8-second backoff after failed attempts finish.
3. Successful recovery leaves output paused.
4. Press Master hotkey to reactivate, then release/repress held triggers.

Rearming is blocked while recovery is unresolved. After retries are exhausted, **Connect** starts a fresh cycle. Repeated offline ticks do not repeatedly publish the same Master pause notification.

Silent UDP loss may not raise an exception. Python cannot cancel a blocked native call; responsiveness can still be affected. Physical passthrough depends on box power/USB behavior, not this application's guarantees.

See [KMBox investigation](docs/kmbox-health.md) for SDK evidence and supervised validation steps. No HID action is sent as a heartbeat probe.

## Profiles and compatibility

Settings save to JSON. Missing legacy fields receive the defaults shown in the GUI instead of inheriting previous-profile settings. Empty patterns are handled safely; malformed nodes and nonpositive divisor values are rejected. Rapid settings edits retain the latest values for the worker.

Back up personal profiles before sharing/manual editing. Simulation checks configuration, not gameplay calibration or hardware behavior.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| KMNet import fails | Windows x64 Python 3.11 and bundled `.pyd` |
| READY but no output | Master/module state, trigger/ADS and actual device configuration; READY is unverified |
| Recovered but no output | Master hotkey, then trigger release/repress |
| Main-PC F8 does nothing | Local keys are read on control PC |
| Extractor finds no image | Working directory and `recoil_processor/inputs` |
| SHAK interval unknown | Measure it; projectile spacing is not a firing interval |
| Makcu connection fails | Unfinished backend |

## Development

See [implementation plan](implementation_plan.md). Planned phases: recovery-policy extraction, supervised heartbeat feasibility, backward-compatible game setups, shared extractor calibration, and saved/editable annotation projects. Planned features are not current support.

Unit tests, GUI smoke checks and physical hardware validation are distinct. No guarantee of zero recoil, removed random spread, exact timing, uninterrupted networking or undetectability. Use only where permitted; you are responsible for game rules and account/hardware risks. Provided as-is without warranty.