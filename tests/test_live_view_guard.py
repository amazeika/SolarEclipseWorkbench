"""The schedule guard: live view gets out of the way of each scheduled shot.

A shot holds the USB lock for roughly 1.4 s on the 80D against a 1.5 s drop
threshold, so a tight contact cluster has only a few hundred milliseconds of slack.
The guard spends none of it: grabs stop 8 s out, and the mirror comes down 3 s out so
the shot finds the body already in its normal state.
"""

import datetime
import os
import threading
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from solareclipseworkbench.camera import LiveViewThread
from solareclipseworkbench.gui import seconds_to_next_camera_job


class _DummyLock:
    def __init__(self):
        self._real = threading.RLock()

    def acquire(self, timeout=None):
        return self._real.acquire(timeout=timeout if timeout is not None else -1)

    def release(self):
        self._real.release()


class _FakeCamera:
    def __init__(self):
        self.name = "Canon EOS 80D"
        self._camera = object()
        self._usb_lock = _DummyLock()


class _Job:
    def __init__(self, func_name, next_run_time):
        def _stub():
            pass
        _stub.__name__ = func_name
        self.func = _stub
        self.next_run_time = next_run_time


class _Scheduler:
    def __init__(self, jobs):
        self._jobs = jobs

    def get_jobs(self):
        return self._jobs


FRAME = b"\xff\xd8\xff\xc0\x00\x11\x08\x01\xe0\x02\x80\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"


def _run_with_provider(provider, settle=0.25, live_view_on=False):
    """Run a worker whose provider returns *seconds to next job*; report what it did."""
    camera = _FakeCamera()
    grabs = []
    live_view_writes = []

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.CameraFile", return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_capture_preview",
                side_effect=lambda *a: grabs.append(True) or 0),
          patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size", return_value=FRAME),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.log_live_view_capabilities"),
          patch("solareclipseworkbench.camera.set_live_view",
                side_effect=lambda cam, on, ctx=None: live_view_writes.append(on) or True)):

        thread = LiveViewThread(camera=camera, frame_callback=lambda _: None,
                                interval_s=0.01, lock_timeout=0.05,
                                next_event_provider=provider)
        thread._live_view_on = live_view_on
        thread.start()
        try:
            thread._stop_event.wait(settle)
            held = thread.held_seconds
            # Snapshot before stop(): teardown always leaves live view, and that write
            # would otherwise mask whether the guard itself did.
            writes = list(live_view_writes)
        finally:
            thread.stop(timeout=2.0)

    return grabs, writes, held


def test_grabs_normally_when_the_next_shot_is_far_off():
    grabs, _, held = _run_with_provider(lambda: 20.0)

    assert grabs, "the guard held frames that were nowhere near a shot"
    assert held is None


def test_grabs_normally_when_no_sequence_is_running():
    grabs, _, held = _run_with_provider(lambda: None)

    assert grabs
    assert held is None


def test_holds_frames_inside_the_guard_but_stays_in_live_view():
    """8 s out: stop grabbing, so any in-flight grab finishes before the exit."""
    grabs, writes, held = _run_with_provider(lambda: 6.0, live_view_on=True)

    assert grabs == [], "a frame was grabbed inside the guard window"
    assert False not in writes, "the mirror came down while still 6 s out"
    assert held == 6.0


def test_drops_out_of_live_view_as_the_shot_closes_in():
    grabs, writes, held = _run_with_provider(lambda: 2.0, live_view_on=True)

    assert grabs == []
    assert writes and writes[-1] is False, "the shot would have paid a mode transition"
    assert held == 2.0


def test_a_provider_that_raises_does_not_stop_live_view():
    def _broken():
        raise RuntimeError("scheduler went away")

    grabs, _, held = _run_with_provider(_broken)

    assert grabs, "a broken provider silently killed the preview"
    assert held is None


def test_only_jobs_that_need_the_camera_count():
    now = datetime.datetime.now(datetime.timezone.utc)
    scheduler = _Scheduler([
        _Job("voice_prompt", now + datetime.timedelta(seconds=2)),
        _Job("execute_command", now + datetime.timedelta(seconds=3)),
        _Job("take_picture", now + datetime.timedelta(seconds=30)),
    ])

    seconds = seconds_to_next_camera_job(scheduler)

    assert seconds == pytest.approx(30, abs=1), \
        "live view stood down for a job that never touches the camera"


def test_reports_the_nearest_camera_job():
    now = datetime.datetime.now(datetime.timezone.utc)
    scheduler = _Scheduler([
        _Job("take_hdr", now + datetime.timedelta(seconds=45)),
        _Job("take_burst", now + datetime.timedelta(seconds=7)),
        _Job("sync_cameras", now + datetime.timedelta(seconds=90)),
    ])

    assert seconds_to_next_camera_job(scheduler) == pytest.approx(7, abs=1)


def test_no_scheduler_and_no_jobs_read_as_nothing_scheduled():
    assert seconds_to_next_camera_job(None) is None
    assert seconds_to_next_camera_job(_Scheduler([])) is None
    assert seconds_to_next_camera_job(_Scheduler([_Job("take_picture", None)])) is None
