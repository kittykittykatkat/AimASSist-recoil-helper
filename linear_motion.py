"""Deterministic movement-only corrections, measured in counts or counts/second."""

BEHAVIORS = ("Single correction", "Smooth correction", "Continuous pull", "Repeat while held")
DEFAULTS = {
    "recoil_motion_mode": "Pattern",
    "linear_behavior": "Single correction",
    "linear_x": 0.0,
    "linear_y": 0.0,
    "linear_delay_ms": 0.0,
    "linear_duration_ms": 100.0,
    "linear_cooldown_ms": 100.0,
    "linear_interval_ms": 250.0,
}


class LinearMotion:
    """Produce incremental movement; cancellation discards pending correction."""

    def __init__(self):
        self.reset()
        self.next_allowed = 0.0
        self.last_time = None
        self.blocked = False

    def reset(self):
        """Cancel movement and discard elapsed-time state from the old sequence."""
        self.started = None
        self.signature = None
        self.previous_total = 0.0
        self.held = False
        self.last_time = None
        self.blocked = False

    def step(self, now: float, active: bool, settings: dict) -> tuple[float, float]:
        signature = tuple(settings[key] for key in DEFAULTS)
        if signature != self.signature:
            changed_while_active = self.signature is not None and active
            self.reset()
            self.signature = signature
            self.blocked = changed_while_active
        if not active:
            self.started = None
            self.held = False
            self.previous_total = 0.0
            self.blocked = False
            self.last_time = None
            return 0.0, 0.0
        if self.blocked:
            return 0.0, 0.0
        if not self.held:
            self.held = True
            if now < self.next_allowed:
                return 0.0, 0.0
            self.started = now
            self.next_allowed = now + settings["linear_cooldown_ms"] / 1000
        if self.started is None:
            return 0.0, 0.0
        elapsed = now - self.started - settings["linear_delay_ms"] / 1000
        if elapsed < 0:
            return 0.0, 0.0
        behavior = settings["linear_behavior"]
        if behavior == "Smooth correction":
            total = min(1.0, elapsed / max(0.001, settings["linear_duration_ms"] / 1000))
        elif behavior == "Continuous pull":
            delta_time = 0.0 if self.last_time is None else min(0.05, max(0.0, now - self.last_time))
            total = self.previous_total + delta_time
        elif behavior == "Repeat while held":
            total = 1 + int(elapsed / max(0.001, settings["linear_interval_ms"] / 1000))
        else:
            total = 1.0
        delta = total - self.previous_total
        if behavior == "Repeat while held":
            delta = min(1.0, delta)
        self.previous_total = total
        self.last_time = now
        return delta * settings["linear_x"], delta * settings["linear_y"]