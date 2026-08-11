"""The pan/zoom viewer.

At 5x the live-view stream is a 1:1 crop of the sensor, so scaling it down to fit a
label discarded pixels the sensor actually resolved. Judging focus needs those pixels
on screen at 1:1 or larger, and needs the view to hold still while frames stream
underneath at 10 fps.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.gui import PreviewView


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def _frame(width=1200, height=800, colour="#404040"):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(colour))
    return pixmap


@pytest.fixture
def view(_qapp):
    widget = PreviewView()
    widget.resize(600, 400)
    yield widget
    widget.deleteLater()


def test_the_scene_matches_the_frame_so_nothing_is_cropped(view):
    view.set_frame(_frame())

    assert (view.sceneRect().width(), view.sceneRect().height()) == (1200, 800)


def test_zoom_survives_the_next_frame(view):
    """Frames arrive at 10 fps; a view that reset would be unusable for focusing."""
    view.set_frame(_frame())
    view.set_scale(4.0)

    for _ in range(5):
        view.set_frame(_frame())

    assert view.current_scale() == pytest.approx(4.0)


def test_a_zoom_change_on_the_camera_refits(view):
    """1x and 5x stream different sizes; the old scene rect would misplace everything."""
    view.set_frame(_frame(960, 640))
    view.fit()

    view.set_frame(_frame(1200, 800))

    assert (view.sceneRect().width(), view.sceneRect().height()) == (1200, 800)


def test_pixels_are_shown_unsmoothed_at_or_above_one_to_one(view):
    """Smoothing at 400% invents detail and makes a defocused limb look acceptable."""
    view.set_frame(_frame())

    view.set_scale(4.0)
    assert view._item.transformationMode() is Qt.TransformationMode.FastTransformation

    view.set_scale(1.0)
    assert view._item.transformationMode() is Qt.TransformationMode.FastTransformation


def test_reduction_is_smoothed(view):
    view.set_frame(_frame())

    view.fit()   # 1200x800 into 600x400 is a reduction

    assert view.current_scale() < 1.0
    assert view._item.transformationMode() is Qt.TransformationMode.SmoothTransformation


def test_resizing_the_window_only_moves_a_fitted_view(view):
    view.set_frame(_frame())
    view.set_scale(2.0)

    view.resize(900, 700)

    assert view.current_scale() == pytest.approx(2.0), \
        "an explicit zoom was undone by a resize"


def test_a_fitted_view_keeps_tracking_the_window(view):
    view.set_frame(_frame())
    view.fit()

    view.resize(1000, 800)

    assert view._fit_mode is True, "the view stopped following the window"


def test_fit_scales_the_frame_to_the_viewport(view):
    view.set_frame(_frame(1200, 800))

    view.fit()

    # Reduction limited by whichever viewport dimension runs out first.
    expected = min(view.viewport().width() / 1200, view.viewport().height() / 800)
    assert view.current_scale() == pytest.approx(expected, rel=0.02)


def test_the_wheel_will_not_zoom_past_its_limits(view):
    view.set_frame(_frame())

    view.set_scale(view._MAX_SCALE)
    view.wheelEvent(_wheel(120))
    assert view.current_scale() <= view._MAX_SCALE

    view.set_scale(view._MIN_SCALE)
    view.wheelEvent(_wheel(-120))
    assert view.current_scale() >= view._MIN_SCALE


def test_the_reticle_is_rebuilt_on_the_new_frame_size(view):
    view.set_frame(_frame(960, 640))
    assert len(view._crosshair) == 2

    view.set_frame(_frame(1200, 800))

    assert len(view._crosshair) == 2, "reticle lines accumulated across frame sizes"
    # The vertical line has no horizontal extent; the horizontal line spans the width.
    vertical, horizontal = sorted(view._crosshair, key=lambda line: line.line().dx())
    assert vertical.line().x1() == pytest.approx(600)
    assert horizontal.line().y1() == pytest.approx(400)


def test_the_centring_overlay_draws_the_limb_and_the_tolerance(view):
    view.set_frame(_frame(960, 640))

    view.show_centring((480.0, 320.0), 75.0, (177.0, 17.0), within=True)

    # Tolerance ellipse, fitted limb, and two centre-marker lines.
    assert len(view._overlay) == 4


def test_the_overlay_warns_when_the_corona_would_clip(view):
    view.set_frame(_frame(960, 640))

    view.show_centring((480.0, 260.0), 75.0, (177.0, 17.0), within=False)
    outside = view._overlay[0].pen().color().name()
    view.show_centring((480.0, 320.0), 75.0, (177.0, 17.0), within=True)
    inside = view._overlay[0].pen().color().name()

    assert outside != inside, "the tolerance ring says the same thing either way"


def test_the_overlay_does_not_accumulate_across_frames(view):
    view.set_frame(_frame(960, 640))

    for _ in range(5):
        view.show_centring((480.0, 320.0), 75.0, (177.0, 17.0), within=True)

    assert len(view._overlay) == 4


def test_a_camera_zoom_change_drops_a_stale_overlay(view):
    """The 1x fit describes the whole disc; at 5x those coordinates mean nothing."""
    view.set_frame(_frame(960, 640))
    view.show_centring((480.0, 320.0), 75.0, (177.0, 17.0), within=True)

    view.set_frame(_frame(1200, 800))

    assert view._overlay == []


def _wheel(delta):
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent

    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
