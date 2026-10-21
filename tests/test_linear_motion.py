from linear_motion import DEFAULTS, LinearMotion


def settings(**values):
    return dict(DEFAULTS, linear_x=10.0, linear_y=20.0, **values)


def test_single_requires_release():
    motion = LinearMotion()
    state = settings()
    assert motion.step(1, True, state) == (10, 20)
    assert motion.step(2, True, state) == (0, 0)
    motion.step(3, False, state)
    assert motion.step(4, True, state) == (10, 20)


def test_smooth_delivers_total_and_cancels():
    motion = LinearMotion()
    state = settings(linear_behavior="Smooth correction", linear_duration_ms=1000)
    assert motion.step(0, True, state) == (0, 0)
    assert motion.step(0.5, True, state) == (5, 10)
    assert motion.step(1, True, state) == (5, 10)
    assert motion.step(2, True, state) == (0, 0)
    assert motion.step(3, False, state) == (0, 0)


def test_delay_repeat_and_continuous_are_time_based():
    motion = LinearMotion()
    state = settings(linear_behavior="Repeat while held", linear_delay_ms=100, linear_interval_ms=500)
    assert motion.step(0, True, state) == (0, 0)
    assert motion.step(0.2, True, state) == (10, 20)
    assert motion.step(0.7, True, state) == (10, 20)
    motion = LinearMotion()
    state = settings(linear_behavior="Continuous pull")
    motion.step(0, True, state)
    assert motion.step(0.5, True, state) == (0.5, 1.0)


def test_settings_edit_requires_release_and_repeat_does_not_catch_up():
    motion = LinearMotion()
    state = settings()
    motion.step(0, True, state)
    state["linear_y"] = 30
    assert motion.step(1, True, state) == (0, 0)
    motion.step(2, False, state)
    assert motion.step(3, True, state) == (10, 30)
    motion = LinearMotion()
    state = settings(linear_behavior="Repeat while held")
    motion.step(0, True, state)
    assert motion.step(5, True, state) == (10, 20)


def test_cooldown_blocks_press_until_release():
    motion = LinearMotion()
    state = settings(linear_cooldown_ms=1000)
    motion.step(0, True, state)
    motion.step(0.1, False, state)
    assert motion.step(0.2, True, state) == (0, 0)
    assert motion.step(2, True, state) == (0, 0)