"""Live-view teardown: the mirror comes down, and nothing races libgphoto2.

Two properties are pinned here. The worker must drop out of live view on both pause
and stop, because pausing exists to get the sensor covered before the solar filter
comes off. And stop() must join, because disconnect() calls exit() on the GUI thread
while the worker may still be inside a preview call -- libgphoto2 is not thread-safe,
and that combination segfaults rather than raising.
"""

import os
import threading
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from solareclipseworkbench.camera import (
    GPhotoCameraAdapter,
    LiveViewThread,
    reset_live_view_widget_cache,
)


class _DummyLock:
    """RLock stand-in that records contention without needing a real camera."""

    def __init__(self, grant=True):
        self._grant = grant
        self._real = threading.RLock()
        self.denied = 0

    def acquire(self, timeout=None):
        if not self._grant:
            self.denied += 1
            return False
        return self._real.acquire(timeout=timeout if timeout is not None else -1)

    def release(self):
        self._real.release()


class _FakeCamera:
    def __init__(self, grant_lock=True):
        self.name = "Canon EOS 80D"
        self._camera = object()
        self._usb_lock = _DummyLock(grant=grant_lock)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_live_view_widget_cache()
    yield
    reset_live_view_widget_cache()


def _run_thread(camera, on_frame, calls, act):
    """Start a worker with gphoto2 stubbed out, run *act*, and return live-view writes."""
    frame = b"\xff\xd8\xff\xc0\x00\x11\x08\x01\xe0\x02\x80\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.CameraFile", return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_capture_preview", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size", return_value=frame),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.log_live_view_capabilities"),
          patch("solareclipseworkbench.camera.set_live_view",
                side_effect=lambda cam, on, ctx=None: calls.append(on) or True)):

        thread = LiveViewThread(camera=camera, frame_callback=on_frame,
                                interval_s=0.01, lock_timeout=0.05)
        thread.start()
        try:
            act(thread)
        finally:
            joined = thread.stop(timeout=2.0)
    return thread, joined


def test_stop_joins_the_worker_and_leaves_live_view():
    camera = _FakeCamera()
    calls = []
    got_frame = threading.Event()

    thread, joined = _run_thread(
        camera, lambda _: got_frame.set(), calls,
        lambda t: got_frame.wait(1.0),
    )

    assert joined is True
    assert not thread.is_alive(), "stop() returned while the worker was still running"
    assert calls[0] is True, "live view was never entered explicitly"
    assert calls[-1] is False, "the worker exited without dropping the mirror"


def test_pause_drops_out_of_live_view_rather_than_just_freezing():
    camera = _FakeCamera()
    calls = []
    got_frame = threading.Event()
    left = threading.Event()

    def _record(cam, on, ctx=None):
        calls.append(on)
        if on is False:
            left.set()
        return True

    frame = b"\xff\xd8\xff\xc0\x00\x11\x08\x01\xe0\x02\x80\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.CameraFile", return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_capture_preview", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size", return_value=frame),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.log_live_view_capabilities"),
          patch("solareclipseworkbench.camera.set_live_view", side_effect=_record)):

        thread = LiveViewThread(camera=camera, frame_callback=lambda _: got_frame.set(),
                                interval_s=0.01, lock_timeout=0.05)
        thread.start()
        try:
            assert got_frame.wait(1.0), "no frame arrived before the pause"
            thread.pause()
            assert left.wait(1.0), "pause did not take the camera out of live view"
        finally:
            thread.stop(timeout=2.0)


def test_a_busy_usb_lock_defers_the_exit_instead_of_queueing_behind_a_shot():
    """A preview thread must never wait on the lock a scheduled shot is holding."""
    camera = _FakeCamera(grant_lock=False)
    calls = []

    thread = LiveViewThread(camera=camera, frame_callback=lambda _: None,
                            interval_s=0.01, lock_timeout=0.05)
    thread._live_view_on = True

    with patch("solareclipseworkbench.camera.set_live_view",
               side_effect=lambda cam, on, ctx=None: calls.append(on) or True):
        assert thread._leave_live_view(object(), object(), 0.05) is False

    assert calls == [], "the widget was written without holding the USB lock"
    assert thread._live_view_on is True, "the retry flag was cleared after a failed exit"
    assert camera._usb_lock.denied == 1


def test_a_caller_can_wait_for_the_mirror_to_actually_come_down():
    """pause() only asks; the worker acts on its next tick.  A still capture that
    shoots before then drags the body out of live view itself."""
    camera = _FakeCamera()
    got_frame = threading.Event()
    frame = b"\xff\xd8\xff\xc0\x00\x11\x08\x01\xe0\x02\x80\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.CameraFile", return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_capture_preview", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size", return_value=frame),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.log_live_view_capabilities"),
          patch("solareclipseworkbench.camera.set_live_view", return_value=True)):

        thread = LiveViewThread(camera=camera, frame_callback=lambda _: got_frame.set(),
                                interval_s=0.01, lock_timeout=0.05)
        thread.start()
        try:
            assert got_frame.wait(1.0)
            # Live view is engaged, so the wait must not report the mirror down.
            assert thread.wait_for_live_view_off(0.0) is False

            thread.pause()

            assert thread.wait_for_live_view_off(2.0) is True
        finally:
            thread.stop(timeout=2.0)


def test_the_mirror_reads_as_down_before_any_frame_is_grabbed():
    camera = _FakeCamera()
    thread = LiveViewThread(camera=camera, frame_callback=lambda _: None)

    assert thread.wait_for_live_view_off(0.0) is True


def test_disconnect_skips_exit_rather_than_racing_a_call_in_flight():
    camera = GPhotoCameraAdapter.__new__(GPhotoCameraAdapter)
    camera.name = "Canon EOS 80D"
    camera._connected = True
    camera._usb_lock = _DummyLock(grant=False)
    exited = []
    camera._camera = type("_Gp", (), {"exit": lambda self: exited.append(True)})()

    with (patch("solareclipseworkbench.camera._DISCONNECT_LOCK_WAIT_S", 0.01),
          patch("solareclipseworkbench.camera.set_live_view") as write):
        camera.disconnect()

    assert exited == [], "exit() ran while another thread was inside libgphoto2"
    assert not write.called
    assert camera._connected is False


def test_disconnect_takes_the_lock_and_leaves_live_view_before_exit():
    order = []
    camera = GPhotoCameraAdapter.__new__(GPhotoCameraAdapter)
    camera.name = "Canon EOS 80D"
    camera._connected = True
    camera._usb_lock = _DummyLock()
    camera._camera = type("_Gp", (), {"exit": lambda self: order.append("exit")})()

    with patch("solareclipseworkbench.camera.set_live_view",
               side_effect=lambda cam, on, ctx=None: order.append(f"live_view={on}")):
        camera.disconnect()

    assert order == ["live_view=False", "exit"]
    assert camera._connected is False
