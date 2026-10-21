# KMBox health investigation

## What is established

The bundled `kmNet.cp311-win_amd64.pyd` exposes initialization, movement,
monitor setup and button-state reads, but no dedicated ping or monitor-packet
timestamp API. Its function docstrings do not define acknowledgement semantics.
No physical-device probe was performed during this investigation.

Published SDK reference source:

- https://github.com/kvmaibox/kmboxnet/blob/main/c%2B%2B_demo/NetConfig/kmboxNet.cpp
- https://github.com/kvmaibox/kmboxnet/blob/main/c%2B%2B_demo/NetConfig/kmboxNet.h

In that source, initialization and movement call `recvfrom()`. However,
`NetRxReturnHandle()` overwrites its result with `ret=0`, and the callers do
not propagate the receive error before calling it. Consequently, a zero return
is not a trustworthy acknowledgement in this reference implementation.
The header declares receive-timeout errors, but their presence alone does not
prove the implementation returns them.

The source also passes a `timeval` structure to Windows `SO_RCVTIMEO`; Winsock
expects a millisecond DWORD. Do not interpret the source's `tv_sec=3` as a
verified three-second timeout. The reference source is not established as the
exact source/version of the bundled binary. Its flaws are evidence for caution,
not proof of identical binary internals.

## Current application behavior

The worker heartbeat measures Python worker activity, not device reachability.
Native exceptions trigger pause/recovery. Successful initialization stays
READY / UNVERIFIED. Silent packet loss and native stalls may remain undetected.
No new network heartbeat has been enabled by this investigation.

## Safe next validation

1. With the user present, check ICMP reachability without generating HID input.
2. Compare reachability with a deliberately disconnected Ethernet cable in a
   non-game session. ICMP is only a network signal, not proof of KMNet or USB health.
3. Establish the exact SDK/firmware version and documented receive semantics.
4. Before using command acknowledgements, establish that errors are actually
   propagated and calls return within a measured bound.

Do not poll initialization, change device settings, or send mouse commands as
a pretend read-only heartbeat. Do not automatically replay missed movement.
If native calls can block or retain the GIL, process isolation is the relevant
next reliability step; a Python watchdog thread cannot cancel such a call.