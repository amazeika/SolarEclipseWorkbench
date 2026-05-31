#!/usr/bin/env python3
"""Manual hardware bench: trace the post-capture event stream on Canon (#4).

The perf probe showed ~5.4 s/shot is spent in `_wait_for_capture_complete`.
This tool reveals *why*: it fires one `trigger_capture` and logs every
`wait_for_event` result with its timestamp, so we can see whether (and when)
`GP_EVENT_CAPTURE_COMPLETE` actually arrives and what the loop is chewing on.

That determines the Phase 5 fix:
  * CAPTURE_COMPLETE arrives early, then a trailing event stream → return on it,
    skip the drain.
  * CAPTURE_COMPLETE never arrives (only UNKNOWN events) → the loop is waiting
    for a signal this body doesn't send; change the completion condition.
  * CAPTURE_COMPLETE arrives at ~5.4 s → the camera is genuinely busy; shortening
    is unsafe and the lever is elsewhere.

NOT a pytest test — drives hardware and fires the shutter once. Run with the
70D connected (macOS: `sudo pkill -9 PTPCamera` first if needed):

    .venv/bin/python tests/bench/event_trace.py
"""

import collections
import logging
import time

import gphoto2 as gp

from solareclipseworkbench.camera import get_cameras, get_camera_by_port

EVENT_NAMES = {
    gp.GP_EVENT_UNKNOWN: "UNKNOWN",
    gp.GP_EVENT_TIMEOUT: "TIMEOUT",
    gp.GP_EVENT_FILE_ADDED: "FILE_ADDED",
    gp.GP_EVENT_FOLDER_ADDED: "FOLDER_ADDED",
    gp.GP_EVENT_CAPTURE_COMPLETE: "CAPTURE_COMPLETE",
}

MAX_EVENTS = 40
DEADLINE_S = 12.0
PER_WAIT_MS = 3000  # same per-poll timeout the production loop uses


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)

    cams = get_cameras()
    if not cams:
        print("No camera detected. On macOS: sudo pkill -9 PTPCamera, then retry.")
        return 1
    name, port = next(((n, p) for n, p in cams if "Canon" in n), cams[0])
    print(f"Using camera: {name} @ {port}")
    camera = get_camera_by_port(name, port, alias=name)
    target = camera._camera
    ctx = gp.gp_context_new()

    # Set a fast shutter so the exposure itself is not the variable under study.
    try:
        config = gp.check_result(gp.gp_camera_get_config(target, ctx))
        ss = gp.check_result(gp.gp_widget_get_child_by_name(config, "shutterspeed"))
        gp.gp_widget_set_value(ss, "1/1000")
        gp.gp_camera_set_config(target, config, ctx)
        print("Set shutterspeed=1/1000")
    except gp.GPhoto2Error as e:
        print(f"(could not set shutter, continuing: {e})")

    print(f"\nTrigger + event trace (cap {MAX_EVENTS} events / {DEADLINE_S:.0f}s, "
          f"{PER_WAIT_MS}ms per wait):")
    counts = collections.Counter()
    first_capture_complete = None

    t0 = time.perf_counter()
    gp.check_result(gp.gp_camera_trigger_capture(target, ctx))
    for i in range(MAX_EVENTS):
        tev = time.perf_counter()
        try:
            event_type, _ = gp.check_result(gp.gp_camera_wait_for_event(target, PER_WAIT_MS, ctx))
        except gp.GPhoto2Error as e:
            print(f"  wait_for_event error: {e}")
            break
        elapsed = (time.perf_counter() - t0) * 1000
        wait_ms = (time.perf_counter() - tev) * 1000
        name_ = EVENT_NAMES.get(event_type, f"#{event_type}")
        counts[name_] += 1
        marker = ""
        if event_type == gp.GP_EVENT_CAPTURE_COMPLETE and first_capture_complete is None:
            first_capture_complete = elapsed
            marker = "   <<< first CAPTURE_COMPLETE"
        print(f"  [{i:2d}] +{elapsed:8.0f}ms  (wait {wait_ms:6.0f}ms)  {name_}{marker}")
        if (time.perf_counter() - t0) > DEADLINE_S:
            print(f"  >>> {DEADLINE_S:.0f}s deadline reached, stopping")
            break

    print("\nSummary:")
    for nm, c in counts.most_common():
        print(f"  {nm:<18} {c}")
    if first_capture_complete is not None:
        print(f"  first CAPTURE_COMPLETE at +{first_capture_complete:.0f}ms")
    else:
        print("  CAPTURE_COMPLETE: NEVER seen "
              "(=> production loop burns max_events waiting for a signal this body "
              "doesn't send; Phase 5 must change the completion condition)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
