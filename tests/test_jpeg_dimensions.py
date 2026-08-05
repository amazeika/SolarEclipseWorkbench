import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.camera import VirtualCamera, _jpeg_dimensions


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def test_reads_dimensions_of_a_real_jpeg(_qapp):
    frame = VirtualCamera().capture_preview()

    assert _jpeg_dimensions(frame) == (640, 480)


def test_returns_none_when_the_data_is_not_a_jpeg():
    assert _jpeg_dimensions(b"not a jpeg at all") is None


def test_returns_none_when_the_jpeg_is_truncated_before_the_frame_header(_qapp):
    frame = VirtualCamera().capture_preview()

    assert _jpeg_dimensions(frame[:4]) is None


def test_skips_segments_that_precede_the_frame_header():
    # A JPEG whose APP0/JFIF segment sits between SOI and SOF0, which is the
    # normal layout: the scan must step over it rather than misread its payload.
    jpeg = (b"\xff\xd8"
            b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xc0\x00\x11\x08\x01\x2c\x01\xf4\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")

    assert _jpeg_dimensions(jpeg) == (500, 300)
