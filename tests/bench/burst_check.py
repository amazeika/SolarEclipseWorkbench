#!/usr/bin/env python3
"""Manual hardware bench: validate the Canon take_burst fix (#4, Phase 1).

Counts how many frames a single real ``take_burst`` call produces, so you get a
hard number — the Phase 1 metric: a working Canon burst yields many frames
(~14 for a 2 s burst on a 70D at 7 fps continuous-high), the broken
single-frame behaviour yields 1.

Frames are counted via ``GP_EVENT_FILE_ADDED`` events drained from the camera
after the burst.  This is deliberate: gphoto2 caches the card's folder listing
within a session, so re-listing files after a burst returns a stale count.
Counting FILE_ADDED events reflects what the camera actually captured.

This is NOT a pytest test — it drives physical hardware and fires the shutter.
Run it directly with the 70D connected (camera on, mode dial on M, SD card in,
manual focus or AF able to lock; on macOS run `sudo pkill -9 PTPCamera` first
if gphoto2 can't claim it):

    .venv/bin/python tests/bench/burst_check.py [duration_seconds]

Default duration is 2.0 s.
"""

import logging
import sys
import time

import gphoto2 as gp

from solareclipseworkbench.camera import (
    CameraSettings,
    get_cameras,
    get_camera_by_port,
    take_burst,
)


def drain_and_count_file_added(target, ctx, settle_s=8.0):
    """Drain queued camera events, counting GP_EVENT_FILE_ADDED.

    Polls until ``settle_s`` of wall-clock has elapsed with no further events,
    so frames still being flushed to the card after the burst are counted.
    """
    count = 0
    deadline = time.monotonic() + settle_s
    while time.monotonic() < deadline:
        try:
            event_type, _ = gp.check_result(
                gp.gp_camera_wait_for_event(target, 500, ctx))
        except gp.GPhoto2Error:
            break
        if event_type == gp.GP_EVENT_FILE_ADDED:
            count += 1
            deadline = time.monotonic() + settle_s  # reset idle window
        elif event_type == gp.GP_EVENT_TIMEOUT:
            continue
    return count


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    # force=True: override any logging config the project set on import, so the
    # take_burst DEBUG lines ("Set Canon drivemode ...") are visible.
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s", force=True)

    cams = get_cameras()
    if not cams:
        print("No camera detected. On macOS: sudo pkill -9 PTPCamera, then retry.")
        return 1
    name, port = next(((n, p) for n, p in cams if "Canon" in n), cams[0])
    print(f"Using camera: {name} @ {port}")
    camera = get_camera_by_port(name, port, alias=name)
    target = camera._camera
    ctx = gp.gp_context_new()

    settings = CameraSettings(camera_name=name, shutter_speed="1/500", aperture="8", iso=400)

    # Clear any stale queued events so the post-burst count is clean.
    drain_and_count_file_added(target, ctx, settle_s=1.0)

    print(f"Firing take_burst(duration={duration}) ...")
    take_burst(camera, settings, duration)

    frames = drain_and_count_file_added(target, ctx, settle_s=8.0)
    print(f"=> {frames} frame(s) captured from a {duration}s burst "
          f"(broken behaviour = 1; fixed = many, ~14 at 7 fps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
