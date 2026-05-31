"""_wait_for_burst_complete releases once the burst's frames are in.

A Canon burst emits ~15 FILE_ADDED (frames) then a long tail of GP_EVENT_UNKNOWN
status chatter. The settle must release ~frame_idle_ms after the *last* frame --
draining but not waiting out the UNKNOWN tail (which would hold the lock ~9 s and
drop the next contact burst), and not on the *first* frame (which would release
mid-burst and -110 the next shot).

Time is driven by a fake clock that only advances inside the mocked
gp_camera_wait_for_event, so the frame-idle timing is deterministic.
"""

import logging

from unittest.mock import patch

import gphoto2

from solareclipseworkbench import camera as cam


class _Clock:
    def __init__(self):
        self.t = 0.0


class _FakeTime:
    """Stand-in for the `time` module exposing only monotonic()."""
    def __init__(self, clock):
        self._clock = clock

    def monotonic(self):
        return self._clock.t


def _drive(events, dt=0.1, **kwargs):
    """Run _wait_for_burst_complete over a scripted event sequence.

    Each mocked gp_camera_wait_for_event advances the fake clock by ``dt`` and
    returns the next event; once the sequence is exhausted it returns TIMEOUT.
    Returns the number of wait calls made.
    """
    clock = _Clock()
    seq = iter(events)
    calls = {"n": 0}

    def fake_wait(target, ms, ctx):
        clock.t += dt
        calls["n"] += 1
        try:
            return (next(seq), None)
        except StopIteration:
            return (cam.gp.GP_EVENT_TIMEOUT, None)

    with patch.object(cam, "time", _FakeTime(clock)), \
         patch.object(cam.gp, "check_result", side_effect=lambda v: v), \
         patch.object(cam.gp, "gp_camera_wait_for_event", side_effect=fake_wait):
        cam._wait_for_burst_complete(object(), object(), **kwargs)
    return calls["n"]


def _last_log(caplog):
    return caplog.records[-1].getMessage()


def test_releases_after_last_frame_and_ignores_chatter(caplog):
    caplog.set_level(logging.INFO)
    gp = cam.gp
    # 3 frames, then a long UNKNOWN tail. dt=0.1s, frame_idle=1.0s -> release
    # 1.0s (10 polls) after the 3rd frame, leaving most of the tail untouched.
    n = _drive([gp.GP_EVENT_FILE_ADDED] * 3 + [gp.GP_EVENT_UNKNOWN] * 30,
               dt=0.1, frame_idle_ms=1000, max_total_ms=12000)
    msg = _last_log(caplog)
    assert "3 frame event(s)" in msg
    assert "stop: frames_settled" in msg
    assert "FILE_ADDED:3" in msg and "UNKNOWN:10" in msg
    # 3 frames + 10 chatter polls = 13; the remaining 20 UNKNOWN were NOT awaited.
    assert n == 13


def test_does_not_release_on_first_frame(caplog):
    caplog.set_level(logging.INFO)
    gp = cam.gp
    # A second frame arrives within frame_idle of the first -> must keep waiting,
    # so the final frame count is 2 (it did not stop after frame #1).
    _drive([gp.GP_EVENT_FILE_ADDED, gp.GP_EVENT_UNKNOWN, gp.GP_EVENT_UNKNOWN,
            gp.GP_EVENT_FILE_ADDED] + [gp.GP_EVENT_UNKNOWN] * 30,
           dt=0.1, frame_idle_ms=1000)
    assert "2 frame event(s)" in _last_log(caplog)


def test_quiet_before_any_frame_exits_immediately(caplog):
    caplog.set_level(logging.INFO)
    gp = cam.gp
    # No frames, queue goes quiet (sequence exhausts -> TIMEOUT) -> idle_no_frames.
    _drive([gp.GP_EVENT_UNKNOWN, gp.GP_EVENT_UNKNOWN], dt=0.1, frame_idle_ms=1000)
    assert "stop: idle_no_frames" in _last_log(caplog)


def test_max_total_bounds_an_endless_stream(caplog):
    caplog.set_level(logging.INFO)
    gp = cam.gp
    # UNKNOWN forever, never a frame and never quiet -> bounded by max_total_ms.
    n = _drive([gp.GP_EVENT_UNKNOWN] * 1000, dt=1.0, frame_idle_ms=1000, max_total_ms=12000)
    assert "stop: max_total" in _last_log(caplog)
    assert n <= 13  # ~12 one-second polls before the 12 s ceiling


def test_breaks_on_gphoto_error(caplog):
    caplog.set_level(logging.INFO)

    def boom(target, ms, ctx):
        raise gphoto2.GPhoto2Error(-1)

    clock = _Clock()
    with patch.object(cam, "time", _FakeTime(clock)), \
         patch.object(cam.gp, "check_result", side_effect=lambda v: v), \
         patch.object(cam.gp, "gp_camera_wait_for_event", side_effect=boom):
        cam._wait_for_burst_complete(object(), object())  # returns, does not raise
    assert "stop: error" in _last_log(caplog)
