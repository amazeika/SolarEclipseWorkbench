"""Sharpness measurement for live-view frames.

Focus is the one setting of eclipse day that cannot be corrected afterwards, and a
boiling solar limb is genuinely hard to judge by eye: seeing swings the apparent
sharpness of single frames by a factor of two, so an operator watching the image
cannot tell a good moment from good focus.

The measurement here is the 10-90% edge width of the solar limb, in pixels. It is
exposure-invariant, physically interpretable, and it has a known floor: at 2.02
arcsec/px with 2-4 arcsec daytime seeing a perfectly focused limb lands around
1.5-2.5 px. A reading of 6 px is defocus, not seeing.

Everything here is pure numpy on a greyscale array -- no Qt, no camera -- so it can be
exercised against synthetic images with known blur.

Only meaningful on the magnified (5x) stream, where one preview pixel is one sensor
pixel. At 1x the disc spans ~150 preview pixels and a focused limb transition is
sub-pixel, so the same computation would measure JPEG compression rather than focus.
Callers are responsible for that gate; see ``MIN_USEFUL_DISC_RADIUS_PX``.
"""

import logging

import numpy as np

LOGGER = logging.getLogger(__name__)

# Fraction of the crop that may sit at full scale before the limb profile is
# untrustworthy. A saturated limb has its bright shoulder clipped flat, which moves the
# 90% level down into the transition and reads as a narrower -- sharper -- edge than
# reality. With an ND 5.0 filter on a bright disc this is easy to hit.
CLIPPING_FRACTION = 0.005

# Below this the disc is too small in the frame for the edge profile to mean anything.
MIN_USEFUL_DISC_RADIUS_PX = 40.0

# Where the profile is sampled, as a fraction of the bright level.
_LOW, _HIGH = 0.1, 0.9


class SharpnessResult:
    """Outcome of one measurement.

    ``edge_width_px`` is None when the frame could not be measured; ``reason`` then
    says why, so the UI can tell the operator what to change instead of blanking.
    """

    def __init__(self, edge_width_px=None, laplacian=None, clipped_fraction=0.0,
                 reason=""):
        self.edge_width_px = edge_width_px
        self.laplacian = laplacian
        self.clipped_fraction = clipped_fraction
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.edge_width_px is not None

    @property
    def clipped(self) -> bool:
        return self.clipped_fraction > CLIPPING_FRACTION

    def __repr__(self):
        if not self.ok:
            return f"SharpnessResult(unmeasurable: {self.reason})"
        return (f"SharpnessResult(edge_width_px={self.edge_width_px:.2f}, "
                f"clipped={self.clipped_fraction:.3%})")


def normalised_laplacian_variance(image: np.ndarray) -> float:
    """Variance of the Laplacian, normalised by mean intensity squared.

    A cross-check that works on sunspot detail as well as the limb, but it moves with
    exposure even after normalisation, so it is only ever a relative indicator.
    """
    data = image.astype(np.float64)
    mean = data.mean()
    if mean <= 0:
        return 0.0
    # 4-neighbour discrete Laplacian, interior only.
    laplacian = (data[:-2, 1:-1] + data[2:, 1:-1]
                 + data[1:-1, :-2] + data[1:-1, 2:]
                 - 4.0 * data[1:-1, 1:-1])
    return float(laplacian.var() / (mean ** 2))


def _edge_width_along(profile: np.ndarray, dark: float, bright: float) -> float | None:
    """Distance over which *profile* falls from 90% to 10% of the bright level.

    The profile runs outward from inside the disc, so it descends. Crossings are
    linearly interpolated, which is what lets a well-focused edge report a fractional
    width instead of quantising to whole pixels.
    """
    span = bright - dark
    if span <= 0:
        return None
    high_level = dark + _HIGH * span
    low_level = dark + _LOW * span

    high_at = _first_crossing(profile, high_level)
    low_at = _first_crossing(profile, low_level)
    if high_at is None or low_at is None or low_at <= high_at:
        return None
    return low_at - high_at


def _first_crossing(profile: np.ndarray, level: float) -> float | None:
    """Sub-pixel index where a descending profile first drops below *level*."""
    below = np.flatnonzero(profile <= level)
    if below.size == 0:
        return None
    index = int(below[0])
    if index == 0:
        return 0.0
    previous, current = profile[index - 1], profile[index]
    if previous == current:
        return float(index)
    return (index - 1) + (previous - level) / (previous - current)


def measure_limb_sharpness(image: np.ndarray, centre=None, radius=None,
                           samples: int = 180, profile_px: int = 24) -> SharpnessResult:
    """Average 10-90% limb edge width over the visible arc, in pixels.

    Samples the intensity along the outward normal at *samples* angles and averages the
    per-angle widths. Averaging around the arc is what makes the number stable enough to
    act on: any single radial profile is at the mercy of a seeing cell.

    *centre* and *radius* come from the disc fit when available; otherwise they are
    estimated from the frame, which is adequate for a centred disc.

    The reading compresses above roughly ``profile_px / 2``: an edge wider than the
    sampling window cannot be measured, only bounded. That costs nothing in use --
    resolution is wanted near the minimum, and anything past ~6 px already reads as
    clearly defocused -- but it means large values should be compared as "bad" rather
    than as a ratio.
    """
    data = np.asarray(image, dtype=np.float64)
    if data.ndim != 2 or min(data.shape) < 3:
        return SharpnessResult(reason="frame too small to measure")

    clipped_fraction = float(np.count_nonzero(data >= 255.0) / data.size)
    laplacian = normalised_laplacian_variance(data)

    if centre is None or radius is None:
        estimated = estimate_disc(data)
        if estimated is None:
            return SharpnessResult(laplacian=laplacian,
                                   clipped_fraction=clipped_fraction,
                                   reason="no solar disc found in the frame")
        centre, radius = estimated

    if radius < MIN_USEFUL_DISC_RADIUS_PX:
        return SharpnessResult(laplacian=laplacian, clipped_fraction=clipped_fraction,
                               reason="disc too small in frame; magnify to 5x")

    widths = []
    for angle in np.linspace(0.0, 2.0 * np.pi, samples, endpoint=False):
        profile = _sample_normal(data, centre, radius, angle, profile_px)
        if profile is None:
            continue
        # Levels are taken per-profile: with the moon encroaching, the sky and disc
        # levels differ around the arc, and a global pair would bias the crossings.
        dark = float(np.median(profile[-max(3, profile_px // 6):]))
        bright = float(np.median(profile[:max(3, profile_px // 6)]))
        width = _edge_width_along(profile, dark, bright)
        if width is not None:
            widths.append(width)

    if len(widths) < samples // 8:
        return SharpnessResult(laplacian=laplacian, clipped_fraction=clipped_fraction,
                               reason="limb not measurable in this frame")

    # Median, not mean: a few profiles will cross a sunspot or the lunar edge and
    # report nonsense, and those should not move the reading.
    return SharpnessResult(edge_width_px=float(np.median(widths)),
                           laplacian=laplacian,
                           clipped_fraction=clipped_fraction)


def _sample_normal(data: np.ndarray, centre, radius: float, angle: float,
                   profile_px: int) -> np.ndarray | None:
    """Intensities along the outward radial normal, straddling the limb."""
    height, width = data.shape
    cx, cy = centre
    start = radius - profile_px / 2.0
    offsets = start + np.arange(profile_px, dtype=np.float64)
    xs = cx + offsets * np.cos(angle)
    ys = cy + offsets * np.sin(angle)

    if xs.min() < 0 or ys.min() < 0 or xs.max() >= width - 1 or ys.max() >= height - 1:
        return None
    return _bilinear(data, xs, ys)


def _bilinear(data: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear sample; nearest-neighbour would quantise the edge width to whole px."""
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    fx = xs - x0
    fy = ys - y0
    return (data[y0, x0] * (1 - fx) * (1 - fy)
            + data[y0, x0 + 1] * fx * (1 - fy)
            + data[y0 + 1, x0] * (1 - fx) * fy
            + data[y0 + 1, x0 + 1] * fx * fy)


class RollingEnvelope:
    """Best reading seen over a trailing window.

    Seeing swings single-frame sharpness by a factor of two, so the instantaneous
    number is nearly unreadable while turning a focuser: it is dominated by which
    moment of atmosphere the frame caught. The best value over the last few seconds is
    what actually tracks focus, because the good moments get better as focus improves
    and the atmosphere cannot make a defocused limb sharp.

    The window is short on purpose.  A minimum-over-window suppresses exactly the rise
    that proves focus has been taken past the best point, so a long window does not
    merely delay the "go back" hint -- measured against synthetic focus runs, three
    seconds and above never produce it at all.  Below about a second the opposite
    failure appears: noise manufactures a transient minimum and the hint fires before
    the operator has overshot, which is the error that would actually cost them their
    focus.  One second holds the reading steady to ~0.2 px, well inside the bracket
    margin, and reports an overshoot about two seconds after it happens.

    Times are supplied by the caller rather than read from a clock, so this is
    deterministic and testable.
    """

    def __init__(self, window_s: float = 1.0):
        self.window_s = window_s
        self._samples: list[tuple[float, float]] = []

    def add(self, value: float, now: float) -> float:
        """Record a reading and return the best in the window."""
        self._samples.append((now, value))
        cutoff = now - self.window_s
        self._samples = [(t, v) for t, v in self._samples if t >= cutoff]
        return self.best

    @property
    def best(self) -> float | None:
        """Lowest edge width in the window -- lower is sharper."""
        return min((v for _, v in self._samples), default=None)

    @property
    def count(self) -> int:
        return len(self._samples)

    def clear(self) -> None:
        """Forget everything.  Used when the view changes and old readings no longer
        describe the same thing (a zoom change, or a move to a different limb)."""
        self._samples = []


# Grading bands for the edge width, in pixels.  At 2.02 arcsec/px with 2-4 arcsec
# daytime seeing a perfectly focused limb cannot go below roughly 2.5 px, so the
# scale is anchored to the atmosphere rather than to anything achieved this session.
# Stated in the UI rather than applied silently, since the assumed seeing is the one
# input the operator can sanity-check by looking up.
FOCUS_BANDS = (
    (2.5, "at the seeing limit"),
    (3.5, "close"),
    (5.0, "soft"),
    (float("inf"), "clearly defocused"),
)


def grade_edge_width(edge_width_px: float) -> str:
    """Absolute quality of a reading, needing no history to interpret."""
    for limit, label in FOCUS_BANDS:
        if edge_width_px <= limit:
            return label
    return FOCUS_BANDS[-1][1]


class FocusTracker:
    """Reads the direction of focus travel, and whether a minimum has been passed.

    The distinction that makes this trustworthy is *bracketed* versus *best so far*. A
    naive indicator reports the best reading it has seen and calls it optimal, which is
    wrong on any monotone run: it says OPTIMAL while focus is still improving, and the
    operator stops early. Only a fall followed by a rise proves a minimum was passed,
    and that matches what the hand does anyway -- rack through best focus, then come
    back to it.

    There is no focuser encoder, so distance from optimal can only ever be expressed in
    metric units (px above the minimum) and direction. It is never a focuser position.

    Fed from the rolling envelope rather than instantaneous readings: seeing swings
    single frames by a factor of two and would flip the direction at random.
    """

    #: Change smaller than this is noise, not the operator turning the focuser.
    NOISE_PX = 0.15
    #: Readings spanning less than this cannot establish a trend.
    MIN_SPAN_S = 1.0
    #: How far back "which way is it going now" looks.  Deliberately short: the
    #: question is which way the hand is turning, and a window long enough to span
    #: both arms of a V reports their average, which is the one useless answer.
    TREND_WINDOW_S = 1.0
    #: A rise this far above the minimum confirms the minimum was real.
    BRACKET_MARGIN_PX = 0.3

    SEARCHING = "searching"
    IMPROVING = "improving"
    WORSENING = "worsening"
    BRACKETED = "bracketed"

    def __init__(self):
        self._samples: list[tuple[float, float]] = []
        self._minimum: float | None = None
        self._descended = False
        self._bracketed = False

    def add(self, envelope_value: float, now: float) -> None:
        self._samples.append((now, envelope_value))
        # Only the recent past says anything about which way the focuser is going.
        self._samples = [(t, v) for t, v in self._samples if t >= now - 8.0]

        if self._minimum is None or envelope_value < self._minimum:
            had_previous = self._minimum is not None
            self._minimum = envelope_value
            # A new minimum invalidates an earlier bracket: focus went past what was
            # taken for the bottom, so it was not the bottom.
            self._bracketed = False
            # Reaching a minimum by descending is what makes it a candidate at all.
            # If the very first reading is the lowest, nothing has been proved -- the
            # true minimum may lie further in the untried direction.
            self._descended = self._descended or had_previous
        elif (self._descended
              and envelope_value > self._minimum + self.BRACKET_MARGIN_PX):
            self._bracketed = True

    @property
    def minimum(self) -> float | None:
        """Best envelope reading seen this session."""
        return self._minimum

    @property
    def bracketed(self) -> bool:
        """True once focus has been taken past the minimum and back out again."""
        return self._bracketed

    @property
    def state(self) -> str:
        if len(self._samples) < 2:
            return self.SEARCHING

        last_t, last_v = self._samples[-1]
        if last_t - self._samples[0][0] < self.MIN_SPAN_S:
            return self.SEARCHING

        # Compare against roughly TREND_WINDOW_S ago rather than the start of the
        # history, so a run that has already turned the corner reads as worsening
        # instead of averaging its two arms into "improving".
        earlier = [(t, v) for t, v in self._samples if t <= last_t - self.TREND_WINDOW_S]
        reference = earlier[-1][1] if earlier else self._samples[0][1]

        change = last_v - reference
        if abs(change) < self.NOISE_PX:
            # Not moving.  Say nothing about direction rather than read noise as a
            # trend -- an operator with their hand still must not see "improving".
            return self.BRACKETED if self._bracketed else self.SEARCHING
        return self.WORSENING if change > 0 else self.IMPROVING

    def describe(self, current: float | None = None) -> str:
        """One line for the operator."""
        state = self.state
        if state == self.IMPROVING:
            return "improving — keep going"
        if state == self.WORSENING:
            if self._bracketed and self._minimum is not None:
                above = "" if current is None else f", {current - self._minimum:+.2f} px"
                return f"past best focus — go back (minimum {self._minimum:.2f} px{above})"
            return "getting worse — try the other way"
        if state == self.BRACKETED and self._minimum is not None:
            return f"minimum bracketed at {self._minimum:.2f} px"
        return "searching — turn the focuser"

    def clear(self) -> None:
        self._samples = []
        self._minimum = None
        self._descended = False
        self._bracketed = False


def estimate_disc(data: np.ndarray) -> tuple[tuple[float, float], float] | None:
    """Rough centre and radius of the bright region, from its area.

    A fallback for the sharpness measurement when no fitted disc is supplied. The
    centring overlay does this properly; here it only has to be close enough to put the
    sampled profiles across the limb.
    """
    peak = float(data.max())
    if peak <= 0:
        return None
    mask = data >= 0.5 * peak
    area = int(mask.sum())
    if area < 16:
        return None
    ys, xs = np.nonzero(mask)
    centre = (float(xs.mean()), float(ys.mean()))
    return centre, float(np.sqrt(area / np.pi))
