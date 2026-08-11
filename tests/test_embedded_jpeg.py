"""Digging the usable image out of a raw file.

gphoto2's PREVIEW file type hands over Canon's 160x120 thumbnail, which says nothing
about focus -- the whole reason for capturing a frame to inspect. A CR2 also carries a
large JPEG rendering, so that is what gets pulled out, by scanning for it rather than
decoding the raw.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.camera import _jpeg_dimensions, _largest_embedded_jpeg


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def jpeg(width, height, seed=0):
    """A real JPEG of the given size, with content so it does not compress to nothing."""
    rng = np.random.default_rng(seed)
    data = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    image = QImage(data.tobytes(), width, height, width * 3, QImage.Format.Format_RGB888)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    image.save(buffer, "JPEG")
    return bytes(buffer.data())


def fake_cr2(_qapp, thumbnail=(160, 120), large=(1620, 1080), noise=200_000):
    """A raw-like file: TIFF header, a thumbnail, a large JPEG, and raw sensor noise."""
    rng = np.random.default_rng(7)
    return (b"II\x2a\x00\x10\x00\x00\x00CR\x02\x00"
            + jpeg(*thumbnail, seed=1)
            + rng.integers(0, 255, noise, dtype=np.uint8).tobytes()
            + jpeg(*large, seed=2)
            + rng.integers(0, 255, noise, dtype=np.uint8).tobytes())


def test_the_large_rendering_is_preferred_over_the_thumbnail(_qapp):
    extracted = _largest_embedded_jpeg(fake_cr2(_qapp))

    assert _jpeg_dimensions(extracted) == (1620, 1080)


def test_the_extracted_bytes_are_a_complete_jpeg(_qapp):
    extracted = _largest_embedded_jpeg(fake_cr2(_qapp))

    assert extracted[:3] == b"\xff\xd8\xff"
    assert extracted[-2:] == b"\xff\xd9"
    assert not QImage.fromData(extracted).isNull(), "the extraction does not decode"


def test_the_decoded_image_matches_what_was_embedded(_qapp):
    original = jpeg(1620, 1080, seed=2)
    extracted = _largest_embedded_jpeg(fake_cr2(_qapp))

    assert extracted == original


def test_raw_sensor_noise_does_not_win(_qapp):
    """The start-of-image marker turns up by chance in raw data, and a stray hit can
    parse as an absurd size."""
    rng = np.random.default_rng(3)
    noisy = (rng.integers(0, 255, 2_000_000, dtype=np.uint8).tobytes()
             + jpeg(1024, 768, seed=4)
             + rng.integers(0, 255, 2_000_000, dtype=np.uint8).tobytes())

    extracted = _largest_embedded_jpeg(noisy)

    assert _jpeg_dimensions(extracted) == (1024, 768)


def test_a_file_with_no_image_yields_nothing(_qapp):
    rng = np.random.default_rng(5)

    assert _largest_embedded_jpeg(rng.integers(0, 255, 100_000,
                                               dtype=np.uint8).tobytes()) is None


def test_thumbnail_sized_images_are_ignored(_qapp):
    """A 160x120 thumbnail is what this exists to avoid returning."""
    only_thumb = b"II\x2a\x00" + jpeg(160, 120, seed=6)

    assert _largest_embedded_jpeg(only_thumb) is None
