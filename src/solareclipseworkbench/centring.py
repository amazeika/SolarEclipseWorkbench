"""Where the sun is in the frame, and which way it is drifting.

Two jobs, both measurements the operator would otherwise be eyeballing.

Framing: the corona out to 3 solar radii spans 2.13 degrees against a 2.25 degree
vertical field, so there is only about a tenth of a degree of vertical slack before an
edge of the outer corona is lost. "Somewhere in the middle" is not good enough, and it
looks fine right up until the frames come back cropped.

Drift: the rate the disc walks across the frame is exactly the quantity a daytime
polar-alignment check wants. At 2.02 arcsec/px, the usual target of 20 arcsec over five
minutes is about 2 px/min, so a readout that resolves a pixel per minute turns a
separate procedure into a glance.

Pure numpy -- no Qt, no camera -- so it can be exercised against synthetic discs and
crescents with known geometry.
"""

import logging

import numpy as np

LOGGER = logging.getLogger(__name__)

# Canon EOS 80D at 382 mm; see docs/02_gear_canon_80d.md.
SENSOR_WIDTH_PX = 6000
SENSOR_HEIGHT_PX = 4000
ARCSEC_PER_SENSOR_PX = 2.02

# Field of view and the extent of the corona worth keeping, in degrees.
FOV_HORIZONTAL_DEG = 3.37
FOV_VERTICAL_DEG = 2.25
CORONA_EXTENT_DEG = 2.13


def _tolerance_sensor_px(fov_deg: float) -> float:
    """Half the room left over once the corona is framed, in sensor pixels."""
    slack_deg = max(fov_deg - CORONA_EXTENT_DEG, 0.0) / 2.0
    return slack_deg * 3600.0 / ARCSEC_PER_SENSOR_PX


#: How far the disc centre may sit from the frame centre with the corona still framed.
#: Wildly different in the two axes -- roughly +-1105 against +-107 sensor px -- which
#: is why the guide is an ellipse.  A circle drawn at the horizontal figure would pass
#: a framing that loses the corona top and bottom.
TOLERANCE_X_SENSOR_PX = _tolerance_sensor_px(FOV_HORIZONTAL_DEG)
TOLERANCE_Y_SENSOR_PX = _tolerance_sensor_px(FOV_VERTICAL_DEG)


class DiscFit:
    """A circle fitted through the solar limb."""

    def __init__(self, centre, radius, points_used, residual_px):
        self.centre = centre
        self.radius = radius
        self.points_used = points_used
        self.residual_px = residual_px

    def __repr__(self):
        return (f"DiscFit(centre=({self.centre[0]:.1f}, {self.centre[1]:.1f}), "
                f"radius={self.radius:.1f}, residual={self.residual_px:.2f}px)")


def fit_circle(xs: np.ndarray, ys: np.ndarray):
    """Algebraic least-squares circle through the given points.

    Solves the linear form x^2 + y^2 + Dx + Ey + F = 0, which has a closed-form
    solution and no starting guess -- worth having when this runs on every frame.
    """
    if xs.size < 3:
        return None
    a = np.column_stack([xs, ys, np.ones_like(xs)])
    b = -(xs ** 2 + ys ** 2)
    try:
        (d, e, f), *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None

    cx, cy = -d / 2.0, -e / 2.0
    squared = cx ** 2 + cy ** 2 - f
    if squared <= 0:
        return None
    return (float(cx), float(cy)), float(np.sqrt(squared))


def limb_points(data: np.ndarray, threshold_fraction: float = 0.5,
                max_points: int = 2000):
    """Boundary pixels of the bright region.

    Taken as the outermost lit pixel along each row and column rather than every edge
    pixel: that is cheap, it spreads the samples around the disc instead of clustering
    them where the boundary is jagged, and it naturally favours the outer limb.
    """
    peak = float(data.max())
    if peak <= 0:
        return None
    mask = data >= threshold_fraction * peak
    if mask.sum() < 32:
        return None

    xs, ys = [], []
    rows = np.nonzero(mask.any(axis=1))[0]
    for row in rows:
        lit = np.nonzero(mask[row])[0]
        xs.extend((lit[0], lit[-1]))
        ys.extend((row, row))
    cols = np.nonzero(mask.any(axis=0))[0]
    for col in cols:
        lit = np.nonzero(mask[:, col])[0]
        xs.extend((col, col))
        ys.extend((lit[0], lit[-1]))

    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size > max_points:
        step = xs.size // max_points + 1
        xs, ys = xs[::step], ys[::step]
    return xs, ys


def fit_solar_disc(data: np.ndarray, iterations: int = 3) -> DiscFit | None:
    """Fit the solar limb, rejecting points that are not on it.

    The centroid of the lit area is not usable here.  From first contact onward the
    moon eats into the disc and drags that centroid away from the sun's true centre,
    increasingly so as totality approaches -- which is precisely when the framing has
    to be right.  A circle fitted through the limb stays put, because the sunlit arc
    still belongs to the same circle however much of it is left.

    Points on the lunar edge are rejected by iterated fitting: they sit at the wrong
    distance from the fitted centre, so trimming the worst residuals and refitting
    converges on the solar arc as long as it is the larger one.
    """
    found = limb_points(data)
    if found is None:
        return None
    xs, ys = found

    fit = fit_circle(xs, ys)
    if fit is None:
        return None

    for _ in range(iterations):
        (cx, cy), radius = fit
        distances = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        residuals = np.abs(distances - radius)
        # Median absolute deviation, not standard deviation: the lunar arc is a
        # cluster of gross outliers, and it would inflate a standard deviation enough
        # to keep itself inside the cut.
        median = float(np.median(residuals))
        spread = float(np.median(np.abs(residuals - median))) or 1e-6
        keep = residuals <= median + 3.0 * spread
        if keep.sum() < 16 or keep.all():
            break
        xs, ys = xs[keep], ys[keep]
        refit = fit_circle(xs, ys)
        if refit is None:
            break
        fit = refit

    (cx, cy), radius = fit
    distances = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    return DiscFit(centre=(cx, cy), radius=radius, points_used=int(xs.size),
                   residual_px=float(np.median(np.abs(distances - radius))))


def sensor_px_per_preview_px(preview_width: int) -> float:
    """Scale factor from preview pixels to sensor pixels.

    Derived from the frame rather than assumed: an unmagnified preview is about 6.25
    sensor pixels per preview pixel, a magnified one is 1:1, and using the wrong figure
    silently scales every offset and drift reading.
    """
    if preview_width <= 0:
        return 1.0
    return SENSOR_WIDTH_PX / float(preview_width)


class DriftTracker:
    """Rate the disc is walking across the frame, from a line fitted to its positions.

    A line fit over a minute rather than a difference between two frames: seeing and
    the fit's own noise move the centre by a fraction of a pixel frame to frame, which
    a two-point difference would report as an enormous rate.

    Times come from the caller, so this is deterministic and testable.
    """

    def __init__(self, window_s: float = 60.0, min_span_s: float = 10.0):
        self.window_s = window_s
        self.min_span_s = min_span_s
        self._samples: list[tuple[float, float, float]] = []

    def add(self, centre, now: float) -> None:
        self._samples.append((now, centre[0], centre[1]))
        self._samples = [s for s in self._samples if s[0] >= now - self.window_s]

    def clear(self) -> None:
        self._samples = []

    def rate_px_per_s(self):
        """(dx, dy) in preview px per second, or None when not yet established."""
        if len(self._samples) < 3:
            return None
        times = np.array([s[0] for s in self._samples])
        if times[-1] - times[0] < self.min_span_s:
            return None
        xs = np.array([s[1] for s in self._samples])
        ys = np.array([s[2] for s in self._samples])
        centred = times - times.mean()
        denominator = float((centred ** 2).sum())
        if denominator <= 0:
            return None
        return (float((centred * (xs - xs.mean())).sum() / denominator),
                float((centred * (ys - ys.mean())).sum() / denominator))

    def drift(self, preview_width: int):
        """Drift as (arcsec/min, bearing) or None.

        The bearing is measured in the image -- degrees clockwise from frame-up --
        because SEW does not know how the camera is rotated on the mount, and dressing
        an image angle up as a sky position angle would be a fiction. The operator is
        nudging in image terms anyway.
        """
        rate = self.rate_px_per_s()
        if rate is None:
            return None
        dx, dy = rate
        scale = sensor_px_per_preview_px(preview_width) * ARCSEC_PER_SENSOR_PX
        arcsec_per_min = float(np.hypot(dx, dy) * scale * 60.0)
        # Screen y grows downward, so negate it to measure from frame-up.
        bearing = float((np.degrees(np.arctan2(dx, -dy))) % 360.0)
        return arcsec_per_min, bearing


#: Compass names for a sky bearing, at 45 degree steps from north through east.
_COMPASS = ("north", "north-east", "east", "south-east",
            "south", "south-west", "west", "north-west")


class SkyOrientation:
    """How the image is rotated relative to the sky.

    Nothing in the camera reports this: SEW knows where the sun drifted in the frame,
    but not which way the frame is pointing, so a raw image bearing cannot say which
    mount axis to adjust.

    The sky supplies the missing reference for free. With mount tracking off the sun
    drifts due west at sidereal rate, so the image bearing measured during a short
    untracked run *is* west, and everything else follows from it.

    Assumes a non-mirrored image, which is what a camera at prime focus gives -- there
    is no star diagonal in the path. A mirrored setup reverses the handedness, hence
    the flag.
    """

    #: Position angle of west, measured from north through east.
    _WEST_PA = 270.0

    def __init__(self, west_image_bearing: float | None = None, mirrored: bool = False):
        self.west_image_bearing = west_image_bearing
        self.mirrored = mirrored

    @property
    def calibrated(self) -> bool:
        return self.west_image_bearing is not None

    def sky_bearing(self, image_bearing: float) -> float | None:
        """Image bearing -> sky bearing (0 north, 90 east, 180 south, 270 west)."""
        if not self.calibrated:
            return None
        if self.mirrored:
            return (image_bearing - self.west_image_bearing + self._WEST_PA) % 360.0
        # East lies to the left in a non-mirrored sky image, so turning clockwise in
        # the image runs backwards through position angle.
        return (self._WEST_PA - image_bearing + self.west_image_bearing) % 360.0

    def describe(self, image_bearing: float) -> str | None:
        """Sky direction as a compass word."""
        bearing = self.sky_bearing(image_bearing)
        if bearing is None:
            return None
        return _COMPASS[int((bearing + 22.5) % 360.0 // 45.0)]

    def components(self, arcsec_per_min: float, image_bearing: float):
        """Drift split into (north, east) rates, the axes drift alignment works in.

        Positive north means drifting north; positive east means drifting east. The
        north-south component is the polar-alignment signal; the east-west component is
        mostly tracking-rate error.
        """
        bearing = self.sky_bearing(image_bearing)
        if bearing is None:
            return None
        radians = np.radians(bearing)
        return (float(arcsec_per_min * np.cos(radians)),
                float(arcsec_per_min * np.sin(radians)))


def calibrate_from_untracked_drift(image_bearing: float,
                                   mirrored: bool = False) -> SkyOrientation:
    """Build an orientation from a drift measured with mount tracking switched off.

    The direction the sun wanders with the drive stopped is due west by definition, so
    that one measurement pins the frame to the sky.
    """
    return SkyOrientation(west_image_bearing=image_bearing % 360.0, mirrored=mirrored)


def offset_from_centre(fit: DiscFit, frame_size, preview_width: int):
    """Disc offset from frame centre, and whether it is inside the corona tolerance.

    Returns (dx_px, dy_px, dx_arcmin, dy_arcmin, within_tolerance).
    """
    width, height = frame_size
    dx = fit.centre[0] - width / 2.0
    dy = fit.centre[1] - height / 2.0

    scale = sensor_px_per_preview_px(preview_width)
    arcmin = scale * ARCSEC_PER_SENSOR_PX / 60.0

    # Compared in sensor pixels, where the tolerance is actually defined.
    norm = ((dx * scale) / TOLERANCE_X_SENSOR_PX) ** 2 + \
           ((dy * scale) / TOLERANCE_Y_SENSOR_PX) ** 2
    return dx, dy, dx * arcmin, dy * arcmin, norm <= 1.0


def limb_target(fit: DiscFit, data: np.ndarray) -> tuple[float, float]:
    """A point on the sunlit limb worth magnifying, in preview pixels.

    Focus is judged on a limb, so the magnified view has to land on one.  Once the
    partial phase starts, half the disc's edge is the moon rather than the sun, and
    magnifying there gives a dark edge that reads as hopeless focus at any setting.

    The moon's direction is read off the frame: it covers one side, so the centroid of
    the lit area is pushed away from it, and the moon lies opposite. Aiming ninety
    degrees away from that keeps the target on sunlit limb for the whole partial phase,
    including a thin crescent where the two ends of the arc are all that is left.
    """
    cx, cy = fit.centre
    mask = data >= 0.5 * float(data.max())
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return cx + fit.radius, cy

    to_moon = np.array([cx - float(xs.mean()), cy - float(ys.mean())])
    if np.hypot(*to_moon) < 0.05 * fit.radius:
        # No detectable bite, so any limb point will do.  Left, arbitrarily but
        # predictably -- an operator who knows where it goes can plan around it.
        return cx - fit.radius, cy

    to_moon /= np.hypot(*to_moon)
    height, width = data.shape
    # Both perpendiculars are equally sunlit; take whichever sits further inside the
    # frame, since a target near an edge leaves the magnified box hanging off it.
    candidates = [
        (cx - to_moon[1] * fit.radius, cy + to_moon[0] * fit.radius),
        (cx + to_moon[1] * fit.radius, cy - to_moon[0] * fit.radius),
    ]
    return max(candidates,
               key=lambda p: min(p[0], width - p[0], p[1], height - p[1]))


def zoom_rect_position(target_preview, preview_width: int, zoom: int):
    """Where to put the magnification box so *target_preview* is in its middle.

    Returned in sensor coordinates, which is what eoszoomposition works in -- not
    preview coordinates, a difference of about 6x at 1x.  Feeding it preview values
    addresses only the top-left corner of the sensor.

    The camera snaps the position to whatever step it supports, so this only has to be
    close.  Clamped so the box stays on the sensor; an off-sensor request is the kind
    of out-of-range value that has dropped this body off USB before.
    """
    scale = sensor_px_per_preview_px(preview_width)
    centre_x = target_preview[0] * scale
    centre_y = target_preview[1] * scale

    rect_w = SENSOR_WIDTH_PX / zoom
    rect_h = SENSOR_HEIGHT_PX / zoom
    x = centre_x - rect_w / 2.0
    y = centre_y - rect_h / 2.0
    return (int(round(min(max(x, 0.0), SENSOR_WIDTH_PX - rect_w))),
            int(round(min(max(y, 0.0), SENSOR_HEIGHT_PX - rect_h))))


def tolerance_preview_px(preview_width: int):
    """Tolerance ellipse semi-axes in preview pixels, for drawing.

    At an unmagnified preview this is roughly 177 x 17 px -- much tighter vertically
    than it looks, and not to be rounded up into something reassuring.
    """
    scale = sensor_px_per_preview_px(preview_width)
    return TOLERANCE_X_SENSOR_PX / scale, TOLERANCE_Y_SENSOR_PX / scale
