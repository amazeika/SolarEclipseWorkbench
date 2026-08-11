"""Taking one frame to check an exposure before it matters.

Live view runs its own auto-exposure, so it cannot say whether a given shutter and ISO
through a solar filter actually produce a usable disc. Only a real frame taken with
those settings can, and there is no second chance at the settings once the partial
phase has started.
"""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from solareclipseworkbench.camera import (
    CameraSettings,
    ReviewShot,
    capture_for_review,
)


class _Lock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        pass


class _Camera:
    def __init__(self):
        self.name = "Canon EOS 80D"
        self._camera = object()
        self._usb_lock = _Lock()


class _Path:
    def __init__(self, name, folder="/store_00020001/DCIM/100CANON"):
        self.name = name
        self.folder = folder


SETTINGS = CameraSettings("Canon EOS 80D", "1/2500", "4.7", 400)
JPEG = b"\xff\xd8fake-frame\xff\xd9"


def _patched(file_added=None, file_data=JPEG, get_raises=None):
    """Patch the camera surface capture_for_review touches."""
    events = []
    if file_added is not None:
        events.append((4, file_added))      # GP_EVENT_FILE_ADDED
    events.append((1, None))                # GP_EVENT_TIMEOUT

    def _wait(target, timeout, context):
        return events.pop(0) if events else (1, None)

    # camera_file is an out-parameter, so the real call takes six arguments.
    def _file_get(target, folder, name, kind, camera_file, context):
        if get_raises is not None:
            raise get_raises
        return 0

    return [
        patch("solareclipseworkbench.camera.__adapt_camera_settings",
              return_value=(object(), object())),
        patch("solareclipseworkbench.camera._drain_camera_events"),
        patch("solareclipseworkbench.camera.gp.gp_camera_trigger_capture",
              return_value=0),
        patch("solareclipseworkbench.camera.gp.gp_camera_wait_for_event",
              side_effect=_wait),
        patch("solareclipseworkbench.camera.gp.gp_camera_file_get",
              side_effect=_file_get),
        patch("solareclipseworkbench.camera.gp.gp_file_get_data_and_size",
              return_value=file_data),
        patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
        patch("solareclipseworkbench.camera.gp.GP_EVENT_FILE_ADDED", 4),
        patch("solareclipseworkbench.camera.gp.GP_EVENT_CAPTURE_COMPLETE", 3),
        patch("solareclipseworkbench.camera.gp.GP_EVENT_TIMEOUT", 1),
    ]


def _run(**kwargs):
    patches = _patched(**kwargs)
    for p in patches:
        p.start()
    try:
        return capture_for_review(_Camera(), SETTINGS)
    finally:
        for p in patches:
            p.stop()


def test_a_captured_jpeg_comes_back_for_inspection():
    shot = _run(file_added=_Path("IMG_0042.JPG"))

    assert shot.ok
    assert shot.jpeg == JPEG
    assert shot.name == "IMG_0042.JPG"


def test_a_raw_file_is_inspected_through_its_embedded_preview():
    """Canon puts a JPEG inside every CR2, so a RAW-only body can still be checked
    without a decoder and without changing how it is set to shoot."""
    shot = _run(file_added=_Path("IMG_0042.CR2"))

    assert shot.ok
    assert shot.embedded_preview, "the operator must know this is not the capture"
    assert shot.name == "IMG_0042.CR2"


def test_a_plain_jpeg_is_not_labelled_as_an_embedded_preview():
    shot = _run(file_added=_Path("IMG_0042.JPG"))

    assert shot.ok
    assert not shot.embedded_preview


def test_a_file_that_yields_no_image_reports_rather_than_showing_nothing():
    shot = _run(file_added=_Path("IMG_0042.CR2"), file_data=b"not-an-image")

    assert not shot.ok
    assert "IMG_0042.CR2" in shot.reason


def test_a_shot_that_never_lands_reports_rather_than_hangs():
    shot = _run(file_added=None)

    assert not shot.ok
    assert "did not report a new file" in shot.reason


def test_a_failed_download_says_so():
    import gphoto2

    shot = _run(file_added=_Path("IMG_0042.JPG"),
                get_raises=gphoto2.GPhoto2Error(-1))

    assert not shot.ok
    assert "IMG_0042.JPG" in shot.reason


def test_a_camera_that_cannot_be_configured_is_refused_cleanly():
    with patch("solareclipseworkbench.camera.__adapt_camera_settings",
               return_value=(None, None)):
        shot = capture_for_review(_Camera(), SETTINGS)

    assert not shot.ok
    assert shot.reason


def test_the_review_settings_are_the_ones_programmed():
    """The frame has to be taken with the settings under test, not whatever the body
    happened to be on.  Putting them back afterwards belongs to the window, which owns
    the exposure while the preview is showing it."""
    applied = []

    patches = [p for p in _patched(file_added=_Path("IMG_0042.JPG"))
               if "__adapt_camera_settings" not in str(p)]
    patches.append(patch(
        "solareclipseworkbench.camera.__adapt_camera_settings",
        side_effect=lambda cam, s: applied.append(s) or (object(), object())))
    for p in patches:
        p.start()
    try:
        capture_for_review(_Camera(), SETTINGS)
    finally:
        for p in patches:
            p.stop()

    assert applied == [SETTINGS]


def test_an_unshot_review_reports_not_ok():
    assert not ReviewShot().ok
    assert not ReviewShot(reason="nope").ok
    assert ReviewShot(jpeg=JPEG).ok
