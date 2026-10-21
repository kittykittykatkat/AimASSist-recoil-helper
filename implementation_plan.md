# Implementation Plan

## [Overview]
Improve fault recovery, document actual behavior and prepare reusable game calibration while retaining existing profiles.

Deliver independently: documentation and recovery correctness first, game setup support second, extractor improvements third. Preserve Pattern mathematics, Burst, overlay and user-renamed reference files. No memory access, targeting, generated firing or detection-evasion functionality.

## [Types]
Future `DevicePhase` enum: STOPPED, INITIALIZING, READY_UNVERIFIED, FAULTED, RETRY_WAIT, RETRY_EXHAUSTED. `DeviceHealthSnapshot` fields: phase, attempt/max_attempts integers, optional monotonic next_retry_at/last_worker_tick/last_initialization_at floats, optional last_error string, requires_rearm boolean. Local activity never implies device acknowledgement.

Future `CalibrationMode`: FINALS_LEGACY, MANUAL. `GameSetup`: schema_version integer, game_id/display_name strings, calibration_mode, positive finite manual_x_multiplier/manual_y_multiplier floats, weapon_intervals_ms mapping names to positive finite floats. Initial IDs the_finals, cs2, wardogs, generic. Missing profile game_id defaults to the_finals. Other games begin explicitly manually calibrated.

Future extractor project: version, source-image path/dimensions, game/weapon, interval/scalar, marking mode, optional origin and ordered impacts. Validate before applying.

## [Files]
Workspace root: `C:\Users\Corpse\Desktop\Projects\aim ASSist`.

- Modify `C:\Users\Corpse\Desktop\Projects\aim ASSist\master_control.py`: idempotent fault notification, completion-based retry deadlines, exhaustion message; later consume recovery policy and game setup.
- Rewrite `C:\Users\Corpse\Desktop\Projects\aim ASSist\readme.md`: current installation, controls, extraction, compatibility and honest limitations.
- Preserve `C:\Users\Corpse\Desktop\Projects\aim ASSist\docs\kmbox-health.md`: source evidence and supervised hardware checklist.
- Later add `C:\Users\Corpse\Desktop\Projects\aim ASSist\device_health.py`: GUI/native-independent recovery policy.
- Later add `C:\Users\Corpse\Desktop\Projects\aim ASSist\game_setup.py` and `C:\Users\Corpse\Desktop\Projects\aim ASSist\game_setups.json`: validated shared game calibration without credentials.
- Later modify `C:\Users\Corpse\Desktop\Projects\aim ASSist\recoil_processor\run_extractor.py`: shared settings and consistent coordinate transform.
- Later add `C:\Users\Corpse\Desktop\Projects\aim ASSist\recoil_processor\extractor_project.py`: annotation persistence.
- Later add `C:\Users\Corpse\Desktop\Projects\aim ASSist\docs\game-calibration.md` and `C:\Users\Corpse\Desktop\Projects\aim ASSist\docs\extractor.md`.
- Preserve `C:\Users\Corpse\Desktop\Projects\aim ASSist\recoil_processor\profile_architect OLD.py` and its user rename. Do not restore obsolete startup instructions. Do not alter overlay files, native binaries, credentials or local archives. No destructive profile migration.

## [Functions]
First modify `pause_for_device_fault()` to notify only on transition; `service_device_connection(now)` to base backoff on attempt completion and report exhausted retries. Keep manual Master hotkey rearm after successful recovery.

Later recovery methods in device_health.py: `record_fault(message: str, now: float) -> None`, `request_connection(now: float) -> None`, `retry_due(now: float) -> bool`, `record_initialization(success: bool, now: float, error: str | None = None) -> None`, `snapshot() -> DeviceHealthSnapshot`.

Integrate through `callback_device_connect`, `hardware_consumer_engine`, `_update_device_status_ui` and `shutdown_runtime`, retaining native ownership and reporting blocked cleanup honestly.

Future game_setup.py functions: `load_game_setups(path: Path) -> dict[str, GameSetup]`, `validate_game_setup(value: dict) -> GameSetup`, `save_game_setups(setups: dict[str, GameSetup], path: Path) -> None`, `get_calibration_multipliers(setup: GameSetup, sensitivity: float, ads_multiplier: float, fov: float, ads: bool) -> tuple[float, float]`.

Modify `normalize_profile`, `callback_load_config`, `callback_save_config`, `hardware_consumer_engine` and extractor `get_user_settings` for game association and equivalent legacy calibration. Retain `export_pattern` conversion and interval metadata. Later unify `Viewport.render/s2i/i2s`; add `save_project`/`load_project` with no GUI dependencies. No function removals in first delivery.

## [Classes]
Future `DeviceRecovery`: retry state/deadlines and rearm requirement, no native or GUI calls. Future `GameSetup`: plain validated data. Existing `KMBoxDevice` remains the native boundary; success does not establish an acknowledgement. Existing `LinearMotion` retains movement-only behavior with later explicit reset semantics. Existing `Viewport` gains a shared transform. No class removals.

Defer KMNet process isolation until blocking measurements justify IPC and latency changes; threads cannot cancel native hangs.

## [Dependencies]
No new package or version changes for initial delivery. Use standard-library enums/dataclasses/pathlib/JSON/monotonic clocks later. Preserve pinned GUI and OpenCV/NumPy tool dependencies. MCP is optional validation assistance, not a runtime requirement.

## [Testing]
Baseline 45 tests. Add notification-coalescing and attempt-completion retry tests; retain exhaustion/manual-rearm checks. Later validate setup schemas, unchanged Finals conversion, legacy profiles, extractor transform round trips, SHAK pair widths and ordinary imports. Run compilation/diff checks and GUI smoke where practical. Physical disconnect/timeout/passthrough checks require supervised non-game validation and must be reported separately. No automatic HID heartbeat probes.

## [Implementation Order]
1. Review pending files, preserve user changes and exclude credentials/references from any eventual commit. Push only when requested.
2. Rewrite README around actual current behavior.
3. Fix repeated fault notifications, retry deadlines and exhaustion messaging; validate.
4. Supervised heartbeat feasibility: SDK version, ICMP behavior and native timeout measurement. No fake online state.
5. Extract recovery policy incrementally after behavior is stable.
6. Add Finals legacy and Generic/CS2/WARDOGS manual setups preserving existing profiles.
7. Share setup calibration/intervals with extractor.
8. Improve extractor coordinate accuracy and save/reopen annotations.
9. Reassess process isolation only when measured stalls justify it.

README must distinguish implemented support from planned features; correct extractor commands, local keyboard scope and hardware limitations; remove unsupported invisibility, ban-timing and universal compatibility claims.