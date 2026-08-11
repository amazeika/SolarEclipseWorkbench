"""Limb sharpness measurement, against synthetic discs with known blur.

The property that matters operationally is monotonicity: as focus degrades the number
must rise, every time, with no flat spots or reversals. An operator racking a focuser
is reading the direction of change, not the absolute value, so a metric that wobbles is
worse than none.
"""

import numpy as np
import pytest

from solareclipseworkbench.focus_metrics import (
    CLIPPING_FRACTION,
    RollingEnvelope,
    estimate_disc,
    measure_limb_sharpness,
    normalised_laplacian_variance,
)


def synthetic_disc(radius=120.0, blur=1.0, size=400, brightness=200.0,
                   centre=None, moon_offset=None):
    """A disc with a smooth limb, blurred by a known amount.

    The edge follows an erf-like ramp of width ``blur``, so the 10-90% width is a known
    multiple of it and the two should track each other.
    """
    centre = centre or (size / 2.0, size / 2.0)
    ys, xs = np.mgrid[0:size, 0:size]
    distance = np.sqrt((xs - centre[0]) ** 2 + (ys - centre[1]) ** 2)

    # Smooth step from bright inside to dark outside, over ~blur pixels.
    image = brightness * 0.5 * (1.0 - np.tanh((distance - radius) / max(blur, 1e-6)))

    if moon_offset is not None:
        # A partial phase: a dark disc of the same size, displaced.
        mx, my = centre[0] + moon_offset[0], centre[1] + moon_offset[1]
        moon = np.sqrt((xs - mx) ** 2 + (ys - my) ** 2)
        image *= 0.5 * (1.0 + np.tanh((moon - radius) / max(blur, 1e-6)))

    return np.clip(image, 0, 255)


def test_a_focused_limb_measures_a_narrow_edge():
    result = measure_limb_sharpness(synthetic_disc(blur=0.5))

    assert result.ok, result.reason
    assert result.edge_width_px < 4.0


def test_edge_width_rises_monotonically_as_focus_degrades():
    """The property the operator actually reads while turning the focuser."""
    widths = []
    for blur in (0.5, 1.0, 2.0, 4.0, 8.0):
        result = measure_limb_sharpness(synthetic_disc(blur=blur))
        assert result.ok, f"blur={blur}: {result.reason}"
        widths.append(result.edge_width_px)

    assert widths == sorted(widths), f"not monotonic: {widths}"
    assert all(b - a > 0.5 for a, b in zip(widths, widths[1:])), \
        f"steps too small to read as a change: {widths}"


def test_the_reading_does_not_depend_on_exposure():
    """Exposure changes with the filter and the sun's altitude; focus does not."""
    dim = measure_limb_sharpness(synthetic_disc(blur=2.0, brightness=80.0))
    bright = measure_limb_sharpness(synthetic_disc(blur=2.0, brightness=240.0))

    assert dim.ok and bright.ok
    assert dim.edge_width_px == pytest.approx(bright.edge_width_px, rel=0.15)


def test_a_partial_phase_is_still_measurable():
    """From C1 onward the moon eats the disc; the sunlit arc must still be read."""
    crescent = synthetic_disc(blur=2.0, moon_offset=(90.0, 0.0))

    result = measure_limb_sharpness(crescent)

    assert result.ok, result.reason
    reference = measure_limb_sharpness(synthetic_disc(blur=2.0))
    assert result.edge_width_px == pytest.approx(reference.edge_width_px, rel=0.35)


def test_saturation_is_reported():
    """A clipped limb reads falsely sharp, so the operator has to be told."""
    blown = synthetic_disc(blur=2.0, brightness=600.0)

    result = measure_limb_sharpness(blown)

    assert result.clipped_fraction > CLIPPING_FRACTION
    assert result.clipped


def test_a_correctly_exposed_disc_is_not_flagged():
    result = measure_limb_sharpness(synthetic_disc(blur=2.0, brightness=200.0))

    assert not result.clipped


def test_an_unmagnified_disc_is_refused_rather_than_guessed_at():
    """At 1x the disc spans ~150 px and a focused limb is sub-pixel, so the number
    would describe JPEG compression rather than focus."""
    tiny = synthetic_disc(radius=12.0, blur=1.0, size=100)

    result = measure_limb_sharpness(tiny)

    assert not result.ok
    assert "5x" in result.reason


def test_an_empty_frame_reports_why_rather_than_raising():
    result = measure_limb_sharpness(np.zeros((200, 200)))

    assert not result.ok
    assert result.reason


def test_the_laplacian_falls_as_the_image_softens():
    sharp = normalised_laplacian_variance(synthetic_disc(blur=0.5))
    soft = normalised_laplacian_variance(synthetic_disc(blur=8.0))

    assert sharp > soft


def test_the_envelope_reports_the_best_moment_not_the_last():
    """Seeing swings single frames by 2x; the good moments are what track focus."""
    envelope = RollingEnvelope(window_s=10.0)

    for t, reading in enumerate([4.0, 2.1, 5.0, 4.4]):
        envelope.add(reading, now=float(t))

    assert envelope.best == pytest.approx(2.1)


def test_the_envelope_forgets_readings_that_left_the_window():
    """Otherwise a lucky moment at the start of the session would be reported all
    evening, and racking away from focus would show no change."""
    envelope = RollingEnvelope(window_s=10.0)
    envelope.add(2.0, now=0.0)

    envelope.add(6.0, now=11.0)

    assert envelope.best == pytest.approx(6.0)
    assert envelope.count == 1


def test_a_cleared_envelope_reports_nothing():
    envelope = RollingEnvelope()
    envelope.add(3.0, now=0.0)

    envelope.clear()

    assert envelope.best is None


def test_the_disc_estimate_finds_a_centred_sun():
    image = synthetic_disc(radius=100.0, blur=1.0, size=400)

    (cx, cy), radius = estimate_disc(image)

    assert cx == pytest.approx(200, abs=3)
    assert cy == pytest.approx(200, abs=3)
    assert radius == pytest.approx(100, rel=0.1)
