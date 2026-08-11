"""Disc fitting, offset and drift.

The case that matters is the partial phase. Once the moon bites into the disc, the
centroid of the lit area walks away from the sun's true centre -- and it walks furthest
just before totality, when the framing has to be right. A circle fitted through the
limb has to stay put instead.
"""

import numpy as np
import pytest

from solareclipseworkbench.centring import (
    SkyOrientation,
    limb_target,
    zoom_rect_position,
    calibrate_from_untracked_drift,
    ARCSEC_PER_SENSOR_PX,
    DriftTracker,
    SENSOR_WIDTH_PX,
    TOLERANCE_X_SENSOR_PX,
    TOLERANCE_Y_SENSOR_PX,
    fit_solar_disc,
    offset_from_centre,
    sensor_px_per_preview_px,
    tolerance_preview_px,
)

SIZE = 480


def disc(centre=(240.0, 240.0), radius=120.0, moon_offset=None, moon_radius=None,
         size=SIZE, blur=1.5):
    """A sunlit disc, optionally with the moon encroaching."""
    ys, xs = np.mgrid[0:size, 0:size]
    distance = np.sqrt((xs - centre[0]) ** 2 + (ys - centre[1]) ** 2)
    image = 200.0 * 0.5 * (1.0 - np.tanh((distance - radius) / blur))

    if moon_offset is not None:
        mr = moon_radius or radius
        mx, my = centre[0] + moon_offset[0], centre[1] + moon_offset[1]
        moon = np.sqrt((xs - mx) ** 2 + (ys - my) ** 2)
        image *= 0.5 * (1.0 + np.tanh((moon - mr) / blur))

    return np.clip(image, 0, 255)


def test_a_full_disc_is_found_where_it_is():
    fit = fit_solar_disc(disc(centre=(300.0, 200.0), radius=100.0))

    assert fit is not None
    assert fit.centre[0] == pytest.approx(300, abs=2)
    assert fit.centre[1] == pytest.approx(200, abs=2)
    assert fit.radius == pytest.approx(100, rel=0.03)


@pytest.mark.parametrize("bite", [40.0, 80.0, 120.0])
def test_the_fitted_centre_holds_still_as_the_moon_encroaches(bite):
    """The centroid of the lit area would migrate here; the fitted circle must not."""
    fit = fit_solar_disc(disc(moon_offset=(bite, 0.0)))

    assert fit is not None, f"lost the disc at bite={bite}"
    assert fit.centre[0] == pytest.approx(240, abs=6)
    assert fit.centre[1] == pytest.approx(240, abs=6)
    assert fit.radius == pytest.approx(120, rel=0.08)


def test_the_fit_beats_the_lit_area_centroid_during_a_partial():
    """Quantifies why the extra machinery is there rather than a centroid."""
    image = disc(moon_offset=(70.0, 0.0))

    fit = fit_solar_disc(image)
    mask = image >= 0.5 * image.max()
    ys, xs = np.nonzero(mask)
    centroid_error = abs(float(xs.mean()) - 240)

    assert abs(fit.centre[0] - 240) < centroid_error / 3.0, (
        f"fit off by {abs(fit.centre[0] - 240):.1f} px vs centroid "
        f"off by {centroid_error:.1f} px")


def test_an_empty_frame_yields_no_fit():
    assert fit_solar_disc(np.zeros((200, 200))) is None


def test_the_preview_scale_comes_from_the_frame_width():
    """Using the wrong scale silently multiplies every offset and drift reading."""
    assert sensor_px_per_preview_px(960) == pytest.approx(SENSOR_WIDTH_PX / 960)
    assert sensor_px_per_preview_px(1200) == pytest.approx(5.0)


def test_the_tolerance_is_an_ellipse_not_a_circle():
    """The vertical field is nearly filled by the corona; the horizontal is not."""
    assert TOLERANCE_Y_SENSOR_PX == pytest.approx(107, abs=8)
    assert TOLERANCE_X_SENSOR_PX == pytest.approx(1105, abs=40)
    assert TOLERANCE_X_SENSOR_PX > 8 * TOLERANCE_Y_SENSOR_PX


def test_the_drawn_tolerance_is_as_tight_as_it_really_is():
    """About 17 preview px vertically at 1x -- small, and not to be rounded up."""
    semi_x, semi_y = tolerance_preview_px(960)

    assert semi_y == pytest.approx(17, abs=2)
    assert semi_x == pytest.approx(177, abs=8)


def test_a_centred_disc_is_within_tolerance():
    fit = fit_solar_disc(disc(centre=(240.0, 240.0)))

    *_, within = offset_from_centre(fit, (SIZE, SIZE), preview_width=960)

    assert within


def test_a_small_vertical_error_already_breaks_the_framing():
    """20 preview px up is ~125 sensor px, past the ~107 px vertical tolerance --
    a disc that still looks comfortably centred by eye."""
    fit = fit_solar_disc(disc(centre=(240.0, 220.0)))

    dx, dy, _, _, within = offset_from_centre(fit, (SIZE, SIZE), preview_width=960)

    assert dy == pytest.approx(-20, abs=3)
    assert not within


def test_the_same_error_sideways_is_harmless():
    fit = fit_solar_disc(disc(centre=(260.0, 240.0)))

    *_, within = offset_from_centre(fit, (SIZE, SIZE), preview_width=960)

    assert within, "horizontal room was treated as tightly as vertical"


def test_offsets_are_reported_in_arcminutes_too():
    fit = fit_solar_disc(disc(centre=(340.0, 240.0)))

    _, _, dx_arcmin, _, _ = offset_from_centre(fit, (SIZE, SIZE), preview_width=960)

    expected = 100 * sensor_px_per_preview_px(960) * ARCSEC_PER_SENSOR_PX / 60.0
    assert dx_arcmin == pytest.approx(expected, rel=0.05)


def test_sidereal_drift_reads_back_as_sidereal():
    """Known-answer check of the whole pixels-to-arcsec chain: an unguided mount
    drifts at ~15 arcsec/s, i.e. 900 arcsec/min."""
    tracker = DriftTracker()
    px_per_s = 15.0 / (ARCSEC_PER_SENSOR_PX * sensor_px_per_preview_px(960))

    for second in range(0, 61):
        tracker.add((240.0 + px_per_s * second, 240.0), now=float(second))

    arcsec_per_min, _ = tracker.drift(preview_width=960)

    assert arcsec_per_min == pytest.approx(900, rel=0.02)


def test_a_polar_alignment_grade_drift_is_resolved():
    """The checklist target is <=20 arcsec over 5 min, i.e. ~4 arcsec/min."""
    tracker = DriftTracker()
    px_per_min = 4.0 / (ARCSEC_PER_SENSOR_PX * sensor_px_per_preview_px(960))

    for second in range(0, 61):
        tracker.add((240.0, 240.0 + px_per_min * second / 60.0), now=float(second))

    arcsec_per_min, _ = tracker.drift(preview_width=960)

    assert arcsec_per_min == pytest.approx(4.0, rel=0.1)


def test_drift_bearing_is_measured_from_frame_up():
    tracker = DriftTracker()
    for second in range(0, 61):
        tracker.add((240.0 + 0.5 * second, 240.0), now=float(second))

    _, bearing = tracker.drift(preview_width=960)

    assert bearing == pytest.approx(90, abs=2), "rightward drift should read as 90 deg"


def test_drift_needs_a_long_enough_baseline():
    """Two frames apart would report the fit's own jitter as an enormous rate."""
    tracker = DriftTracker()
    tracker.add((240.0, 240.0), now=0.0)
    tracker.add((241.0, 240.0), now=0.2)
    tracker.add((242.0, 240.0), now=0.4)

    assert tracker.drift(preview_width=960) is None


def test_an_uncalibrated_orientation_admits_it_knows_nothing():
    """Better silent than confidently wrong about which knob to turn."""
    orientation = SkyOrientation()

    assert not orientation.calibrated
    assert orientation.sky_bearing(213.0) is None
    assert orientation.describe(213.0) is None
    assert orientation.components(11.0, 213.0) is None


def test_the_untracked_drift_direction_becomes_west():
    """With the drive stopped the sun goes due west, which is the whole calibration."""
    orientation = calibrate_from_untracked_drift(image_bearing=90.0)

    assert orientation.sky_bearing(90.0) == pytest.approx(270.0)
    assert orientation.describe(90.0) == "west"


@pytest.mark.parametrize("image_bearing, expected", [
    (90.0, "west"),
    (0.0, "north"),     # 90 deg anticlockwise of west in a non-mirrored image
    (270.0, "east"),
    (180.0, "south"),
])
def test_the_compass_follows_from_one_calibration(image_bearing, expected):
    orientation = calibrate_from_untracked_drift(image_bearing=90.0)

    assert orientation.describe(image_bearing) == expected


def test_a_camera_mounted_at_an_angle_is_handled():
    """The camera sits in the clamp however it sits; the calibration absorbs it."""
    orientation = calibrate_from_untracked_drift(image_bearing=143.0)

    assert orientation.describe(143.0) == "west"
    assert orientation.describe(53.0) == "north"


def test_a_mirrored_image_reverses_the_handedness():
    """A star diagonal flips the image, and north lands on the other side of west."""
    normal = calibrate_from_untracked_drift(image_bearing=90.0)
    mirrored = calibrate_from_untracked_drift(image_bearing=90.0, mirrored=True)

    assert normal.describe(0.0) == "north"
    assert mirrored.describe(0.0) == "south"


def test_drift_splits_into_the_axes_alignment_actually_uses():
    """North-south is the polar-alignment signal; east-west is mostly rate error."""
    orientation = calibrate_from_untracked_drift(image_bearing=90.0)

    north, east = orientation.components(10.0, image_bearing=0.0)

    assert north == pytest.approx(10.0, abs=0.01)
    assert east == pytest.approx(0.0, abs=0.01)


def test_pure_westward_drift_shows_no_polar_error():
    orientation = calibrate_from_untracked_drift(image_bearing=90.0)

    north, east = orientation.components(10.0, image_bearing=90.0)

    assert north == pytest.approx(0.0, abs=0.01)
    assert east == pytest.approx(-10.0, abs=0.01)


def test_calibration_survives_a_bearing_given_outside_one_turn():
    orientation = calibrate_from_untracked_drift(image_bearing=450.0)

    assert orientation.west_image_bearing == pytest.approx(90.0)


def test_the_limb_target_avoids_the_moon():
    """Magnifying the lunar edge shows a dark rim that reads as hopeless focus at
    every setting, so the target has to stay on sunlit limb."""
    image = disc(moon_offset=(90.0, 0.0))   # moon encroaching from the right
    fit = fit_solar_disc(image)

    tx, ty = limb_target(fit, image)

    assert abs(tx - 240) < fit.radius * 0.4, "target drifted toward the moon"
    assert abs(ty - 240) == pytest.approx(fit.radius, rel=0.15)


def test_the_limb_target_sits_on_the_limb():
    image = disc()
    fit = fit_solar_disc(image)

    tx, ty = limb_target(fit, image)

    assert np.hypot(tx - 240, ty - 240) == pytest.approx(fit.radius, rel=0.02)


@pytest.mark.parametrize("moon_at", [(90.0, 0.0), (-90.0, 0.0), (0.0, 90.0), (0.0, -90.0)])
def test_the_target_stays_sunlit_whichever_side_the_moon_is_on(moon_at):
    image = disc(moon_offset=moon_at)
    fit = fit_solar_disc(image)

    tx, ty = limb_target(fit, image)

    # Just inside the limb at the target should still be lit.
    inward = (240 + (tx - 240) * 0.9, 240 + (ty - 240) * 0.9)
    assert image[int(inward[1]), int(inward[0])] > 0.4 * image.max()


def test_the_zoom_box_is_positioned_in_sensor_coordinates():
    """eoszoomposition works in sensor pixels; preview values would address only the
    top-left corner of the sensor."""
    x, y = zoom_rect_position((480.0, 320.0), preview_width=960, zoom=5)

    # Frame centre in preview px is sensor centre; the 5x box is 1200x800 sensor px.
    assert x == pytest.approx(SENSOR_WIDTH_PX / 2 - 600, abs=2)
    assert y == pytest.approx(4000 / 2 - 400, abs=2)


def test_the_zoom_box_is_kept_on_the_sensor():
    """An out-of-range value is the kind of write that has dropped this body off USB."""
    x, y = zoom_rect_position((0.0, 0.0), preview_width=960, zoom=5)
    assert (x, y) == (0, 0)

    x, y = zoom_rect_position((960.0, 640.0), preview_width=960, zoom=5)
    assert x == SENSOR_WIDTH_PX - 1200
    assert y == 4000 - 800


def test_drift_ignores_samples_that_left_the_window():
    tracker = DriftTracker(window_s=30.0)
    tracker.add((0.0, 240.0), now=0.0)

    for second in range(40, 101):
        tracker.add((240.0, 240.0), now=float(second))

    arcsec_per_min, _ = tracker.drift(preview_width=960)

    assert arcsec_per_min == pytest.approx(0.0, abs=1.0)
