import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from unittest.mock import patch

import pytest

from solareclipseworkbench.camera import (
    LIVE_VIEW_ZOOM_LEVELS,
    LiveViewThread,
    _set_live_view_zoom,
)


def _jpeg(width, height):
    """Minimal JPEG (SOI + JFIF + SOF0) whose frame header carries the given size."""
    return (b"\xff\xd8"
            b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xc0\x00\x11\x08"
            + height.to_bytes(2, "big") + width.to_bytes(2, "big")
            + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class _DummyLock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        pass


class _GPhotoCameraStub:
    def __init__(self):
        self._camera = object()
        self._usb_lock = _DummyLock()


class _ZoomHarness:
    """Patches the gphoto2 surface LiveViewThread touches and records zoom writes."""

    def __init__(self, fail_zoom_write=False):
        self.frame = _jpeg(500, 300)
        self.zoom_writes = []
        self.drain_calls = 0
        self._fail_zoom_write = fail_zoom_write

    def _get_config(self, target, context):
        if self._fail_zoom_write:
            raise RuntimeError("no eoszoom on this body")
        return object()

    def _set_value(self, widget, value):
        self.zoom_writes.append(value)
        # The real camera switches to the zoomed stream after the write.
        self.frame = _jpeg(800, 532) if value != "1" else _jpeg(500, 300)

    def _drain(self, target, context, timeout_ms=200, max_events=50):
        self.drain_calls += 1

    def patches(self):
        return [
            patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
            patch("solareclipseworkbench.camera.gp.CameraFile", return_value=object()),
            patch("solareclipseworkbench.camera.gp.gp_camera_capture_preview", return_value=0),
            patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size",
                  side_effect=lambda cam_file: self.frame),
            patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
            patch("solareclipseworkbench.camera.gp.gp_camera_get_config",
                  side_effect=self._get_config),
            patch("solareclipseworkbench.camera.gp.gp_widget_get_child_by_name",
                  side_effect=lambda config, name: object()),
            patch("solareclipseworkbench.camera.gp.gp_widget_set_value",
                  side_effect=self._set_value),
            patch("solareclipseworkbench.camera.gp.gp_camera_set_config", return_value=0),
            patch("solareclipseworkbench.camera._drain_camera_events",
                  side_effect=self._drain),
        ]


def _run_thread(harness, body):
    frames = []
    first_frame = threading.Event()

    def on_frame(jpeg_bytes):
        frames.append(jpeg_bytes)
        first_frame.set()

    patches = harness.patches()
    for p in patches:
        p.start()
    thread = LiveViewThread(camera=_GPhotoCameraStub(), frame_callback=on_frame,
                            interval_s=0.001, lock_timeout=0.01)
    thread.start()
    try:
        assert first_frame.wait(2.0), "Timed out waiting for the first preview frame"
        body(thread, frames)
    finally:
        thread.stop()
        thread.join(timeout=2.0)
        for p in patches:
            p.stop()
    return thread


def test_request_zoom_rejects_levels_outside_the_probed_set():
    thread = LiveViewThread(camera=_GPhotoCameraStub(), frame_callback=lambda b: None)

    assert thread.request_zoom(2) is False
    assert thread._zoom_request is None
    assert thread.request_zoom(5) is True


def test_set_live_view_zoom_refuses_unvalidated_levels_before_touching_the_camera():
    with pytest.raises(ValueError):
        _set_live_view_zoom(object(), object(), 2)


def test_worker_applies_requested_zoom_with_event_drain():
    harness = _ZoomHarness()

    def body(thread, frames):
        assert thread.request_zoom(5)
        assert _wait_for(lambda: thread.zoom_level == 5)
        assert _wait_for(lambda: thread.zoom_engaged)

    _run_thread(harness, body)

    assert "5" in harness.zoom_writes
    assert harness.drain_calls >= 1


def test_zoom_state_returns_to_disengaged_at_full_view():
    harness = _ZoomHarness()

    def body(thread, frames):
        thread.request_zoom(5)
        assert _wait_for(lambda: thread.zoom_engaged)
        thread.request_zoom(1)
        assert _wait_for(lambda: not thread.zoom_engaged)
        assert thread.zoom_level == 1

    _run_thread(harness, body)


def test_failed_zoom_write_reports_error_and_keeps_streaming():
    harness = _ZoomHarness(fail_zoom_write=True)

    def body(thread, frames):
        thread.request_zoom(5)
        assert _wait_for(lambda: thread.zoom_error is not None)
        assert thread.zoom_level == 1
        seen = len(frames)
        assert _wait_for(lambda: len(frames) > seen), "Streaming stopped after zoom failure"

    _run_thread(harness, body)

    assert harness.zoom_writes == []


def test_stop_resets_zoom_to_full_view():
    harness = _ZoomHarness()

    def body(thread, frames):
        thread.request_zoom(10)
        assert _wait_for(lambda: thread.zoom_level == 10)

    _run_thread(harness, body)

    assert harness.zoom_writes[-1] == "1"


def test_zoom_button_is_disabled_for_the_virtual_camera():
    from PyQt6.QtWidgets import QApplication

    from solareclipseworkbench.camera import VirtualCamera
    from solareclipseworkbench.gui import LiveViewWindow

    app = QApplication.instance() or QApplication([])
    window = LiveViewWindow(VirtualCamera())
    try:
        assert not window._zoom_btn.isEnabled()
        assert window._zoom_btn.text() == f"Zoom {LIVE_VIEW_ZOOM_LEVELS[1]}×"
    finally:
        window.close()
