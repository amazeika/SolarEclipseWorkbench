"""QImage -> numpy conversion feeding the focus metric.

Qt pads image rows to a 4-byte boundary, so a frame whose width is not a multiple of
four has a row stride wider than the image. Reshaping on width rather than stride
shears the picture progressively down the frame -- which would not crash, and would not
look obviously wrong on a preview, but would quietly corrupt every sharpness reading.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.gui import _qimage_to_grey


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def _rgb_with_marked_edges(width, height=60):
    """Bright left column, dark right column -- shearing moves them off the edges."""
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, 0] = 255
    rgb[:, -1] = (10, 10, 10)
    return QImage(rgb.tobytes(), width, height, width * 3,
                  QImage.Format.Format_RGB888)


# 1200 is the real magnified frame width and pads to nothing; the others force padding.
@pytest.mark.parametrize("width", [1200, 1201, 1202, 1203])
def test_rows_stay_aligned_whatever_the_stride_padding(width, _qapp):
    result = _qimage_to_grey(_rgb_with_marked_edges(width))

    assert result.shape == (60, width)
    # The last row is where progressive shearing would have accumulated.
    assert result[-1, 0] > 200, "left edge lost by row misalignment"
    assert result[-1, -1] < 30, "right edge lost by row misalignment"


def test_padding_really_is_exercised(_qapp):
    """Guards the test above: if Qt stopped padding, those cases would prove nothing."""
    grey = _rgb_with_marked_edges(1201).convertToFormat(
        QImage.Format.Format_Grayscale8)

    assert grey.bytesPerLine() > 1201


def test_luminance_is_a_weighted_mix_not_a_single_channel(_qapp):
    """A green disc must not read as black just because the red channel is empty."""
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    rgb[:, :] = (0, 255, 0)
    image = QImage(rgb.tobytes(), 16, 16, 48, QImage.Format.Format_RGB888)

    result = _qimage_to_grey(image)

    assert result.mean() > 100


def test_the_result_is_float_so_the_metric_can_do_arithmetic(_qapp):
    result = _qimage_to_grey(_rgb_with_marked_edges(64))

    assert result.dtype == np.float64
