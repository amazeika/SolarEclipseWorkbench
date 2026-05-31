"""_wait_for_burst_complete drains until the USB interface is idle.

A burst writes many frames that flush over several seconds. Breaking on the
first GP_EVENT_FILE_ADDED (as _wait_for_capture_complete does) releases the USB
lock mid-flush, so the next scheduled shot fails with -110 (I/O in progress).
_wait_for_burst_complete instead consumes events until a full no-event timeout.
"""

from unittest.mock import patch

import gphoto2

from solareclipseworkbench import camera as cam


def _run_with_events(events, **kwargs):
    """Drive _wait_for_burst_complete with a scripted sequence of event types.

    Returns the number of gp_camera_wait_for_event calls made.
    """
    calls = []

    def fake_wait(target, timeout_ms, context):
        idx = len(calls)
        calls.append(timeout_ms)
        return (events[idx], None)

    with patch.object(cam.gp, "check_result", side_effect=lambda v: v), \
         patch.object(cam.gp, "gp_camera_wait_for_event", side_effect=fake_wait):
        cam._wait_for_burst_complete(object(), object(), **kwargs)
    return calls


def test_consumes_all_frames_then_stops_on_idle():
    gp = cam.gp
    events = [
        gp.GP_EVENT_FILE_ADDED,
        gp.GP_EVENT_FILE_ADDED,
        gp.GP_EVENT_FILE_ADDED,
        gp.GP_EVENT_TIMEOUT,      # interface idle -> done
        gp.GP_EVENT_FILE_ADDED,   # must NOT be consumed (loop already returned)
    ]
    calls = _run_with_events(events, idle_timeout_ms=600, max_waits=60)
    assert calls == [600, 600, 600, 600]  # 3 frames + 1 idle wait, then stop


def test_does_not_stop_on_first_frame():
    # The whole point: a single FILE_ADDED must not end the wait.
    gp = cam.gp
    events = [gp.GP_EVENT_FILE_ADDED, gp.GP_EVENT_CAPTURE_COMPLETE, gp.GP_EVENT_TIMEOUT]
    calls = _run_with_events(events, idle_timeout_ms=500, max_waits=60)
    assert len(calls) == 3  # kept going past the first frame and the capture-complete


def test_respects_max_waits_when_never_idle():
    gp = cam.gp
    # A body that never goes quiet must still be bounded.
    events = [gp.GP_EVENT_FILE_ADDED] * 100
    calls = _run_with_events(events, idle_timeout_ms=10, max_waits=5)
    assert len(calls) == 5


def test_breaks_on_gphoto_error():
    def boom(target, timeout_ms, context):
        raise gphoto2.GPhoto2Error(-1)

    with patch.object(cam.gp, "check_result", side_effect=lambda v: v), \
         patch.object(cam.gp, "gp_camera_wait_for_event", side_effect=boom):
        cam._wait_for_burst_complete(object(), object())  # returns, does not raise
