import pytest

from solareclipseworkbench.camera import (
    CameraSettings,
    _describe_args,
    _serialised_on_camera,
)
from solareclipseworkbench.shot_events import BUS, ShotOutcome


class _FakeLock:
    def __init__(self, acquirable=True):
        self._acquirable = acquirable
        self.released = 0

    def acquire(self, timeout=None):
        return self._acquirable

    def release(self):
        self.released += 1


class _FakeCamera:
    def __init__(self, name="cam0", acquirable=True):
        self.name = name
        self._usb_lock = _FakeLock(acquirable)


def _collect(command):
    """Subscribe a collector to the shared BUS, returning the captured list."""
    events = []
    BUS.subscribe(lambda e: events.append(e) if e.command == command else None)
    return events


def test_wrapper_publishes_fired_with_description():
    events = _collect("take_picture")

    @_serialised_on_camera
    def take_picture(camera, settings):
        return "ok"

    cam = _FakeCamera()
    settings = CameraSettings("cam0", "1/2000", "5.6", 100)
    assert take_picture(cam, settings) == "ok"

    assert len(events) == 1
    evt = events[0]
    assert evt.outcome == ShotOutcome.FIRED
    assert evt.camera_name == "cam0"
    assert evt.description == f"1/2000, {settings.aperture}, 100"
    assert evt.fired_at >= evt.scheduled_at
    assert cam._usb_lock.released == 1


def test_wrapper_publishes_dropped_when_lock_busy():
    events = _collect("take_burst")

    @_serialised_on_camera
    def take_burst(camera, settings, duration):
        raise AssertionError("must not run when lock is busy")

    cam = _FakeCamera(acquirable=False)
    settings = CameraSettings("cam0", "1/1000", "8", 200)
    assert take_burst(cam, settings, 3.0) is None

    assert len(events) == 1
    evt = events[0]
    assert evt.outcome == ShotOutcome.DROPPED
    assert evt.fired_at == evt.scheduled_at  # sentinel: never ran
    assert cam._usb_lock.released == 0  # lock was never acquired


def test_wrapper_publishes_failed_and_reraises():
    events = _collect("take_hdr")

    @_serialised_on_camera
    def take_hdr(camera, settings, stops):
        raise ValueError("boom")

    cam = _FakeCamera()
    settings = CameraSettings("cam0", "1/500", "11", 400)
    with pytest.raises(ValueError, match="boom"):
        take_hdr(cam, settings, 5)

    assert len(events) == 1
    evt = events[0]
    assert evt.outcome == ShotOutcome.FAILED
    assert "ValueError: boom" == evt.detail
    assert cam._usb_lock.released == 1  # released even on failure


def test_event_camera_name_comes_from_settings_not_object():
    # The live camera object's name (gphoto2 model, with suffix) differs from the script
    # name in CameraSettings; the event must carry the script name so it matches the table.
    events = _collect("take_picture")

    @_serialised_on_camera
    def take_picture(camera, settings):
        return "ok"

    cam = _FakeCamera(name="Canon EOS 1100D (PTP mode)")
    settings = CameraSettings("1100D", "1/2000", "5.6", 100)
    take_picture(cam, settings)

    assert len(events) == 1
    assert events[0].camera_name == "1100D"


def test_describe_args_capture_and_fallback():
    s = CameraSettings("cam0", "1/2000", "5.6", 100)
    assert _describe_args("take_picture", (s,), {}) == f"1/2000, {s.aperture}, 100"
    assert _describe_args("take_burst", (s, 3.0), {}) == f"1/2000, {s.aperture}, 100, 3.0s"
    assert _describe_args("take_hdr", (s, 5), {}) == f"1/2000, {s.aperture}, 100, 5 stops"
    assert _describe_args("take_bracket", (s, "1/3"), {}) == f"1/2000, {s.aperture}, 100, 1/3"
    # Non-capture command falls back to a plain repr.
    assert _describe_args("sync_cameras", (), {}) == ""
    assert _describe_args("voice_prompt", ("hello",), {}) == "'hello'"
