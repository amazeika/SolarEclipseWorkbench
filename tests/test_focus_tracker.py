"""The focus quality indicator.

Its whole value rests on one distinction: a minimum that has been *bracketed* -- racked
through and back -- versus merely the best reading seen so far. Reporting the latter as
optimal is wrong on any monotone run, and wrong in the direction that costs the
operator their focus, because it tells them to stop while focus is still improving.
"""

import pytest

from solareclipseworkbench.focus_metrics import FocusTracker, grade_edge_width


def _feed(tracker, readings, start=0.0, step=0.5):
    for index, value in enumerate(readings):
        tracker.add(value, now=start + index * step)
    return tracker


def test_a_monotone_improvement_is_never_called_optimal():
    """The failure mode a naive best-so-far indicator has: focus is still improving."""
    tracker = _feed(FocusTracker(), [8.0, 6.5, 5.0, 4.0, 3.2])

    assert tracker.state == FocusTracker.IMPROVING
    assert not tracker.bracketed
    assert "keep going" in tracker.describe()


def test_falling_then_rising_brackets_the_minimum():
    tracker = _feed(FocusTracker(), [6.0, 4.0, 2.2, 2.8, 3.6])

    assert tracker.bracketed
    assert tracker.minimum == pytest.approx(2.2)
    assert "go back" in tracker.describe()


def test_the_bracketed_minimum_is_reported_with_the_distance_from_it():
    tracker = _feed(FocusTracker(), [6.0, 4.0, 2.2, 2.8, 3.6])

    description = tracker.describe(current=3.6)

    assert "2.20" in description
    assert "+1.40" in description


def test_a_still_hand_is_not_read_as_a_trend():
    """Seeing noise must not turn into 'improving' while the operator is not moving."""
    tracker = _feed(FocusTracker(), [3.00, 3.05, 2.98, 3.02, 3.01])

    assert tracker.state == FocusTracker.SEARCHING
    assert "turn the focuser" in tracker.describe()


def test_a_bracketed_minimum_survives_the_hand_stopping():
    tracker = _feed(FocusTracker(), [6.0, 3.0, 2.0, 2.9])
    assert tracker.bracketed

    _feed(tracker, [2.90, 2.91, 2.89, 2.90], start=10.0)

    assert tracker.bracketed
    assert "bracketed" in tracker.describe() or "go back" in tracker.describe()


def test_going_past_a_supposed_minimum_invalidates_the_bracket():
    """The operator kept turning and found genuinely better focus, so the earlier
    'minimum' was not one."""
    tracker = _feed(FocusTracker(), [6.0, 3.0, 3.5])
    assert tracker.bracketed

    _feed(tracker, [2.0], start=10.0)

    assert not tracker.bracketed
    assert tracker.minimum == pytest.approx(2.0)


def test_a_single_reading_says_nothing():
    tracker = FocusTracker()
    tracker.add(3.0, now=0.0)

    assert tracker.state == FocusTracker.SEARCHING


def test_readings_too_close_together_say_nothing():
    """Two frames 30 ms apart cannot establish which way a focuser is turning."""
    tracker = FocusTracker()
    tracker.add(6.0, now=0.0)
    tracker.add(3.0, now=0.03)

    assert tracker.state == FocusTracker.SEARCHING


def test_worsening_without_a_bracket_suggests_reversing():
    tracker = _feed(FocusTracker(), [2.5, 3.5, 4.5, 5.5])

    assert tracker.state == FocusTracker.WORSENING
    assert "other way" in tracker.describe()


def test_clearing_forgets_the_session():
    tracker = _feed(FocusTracker(), [6.0, 3.0, 2.0, 2.8])

    tracker.clear()

    assert tracker.minimum is None
    assert not tracker.bracketed
    assert tracker.state == FocusTracker.SEARCHING


def test_a_long_envelope_would_hide_the_overshoot_entirely():
    """Why the envelope window is short.

    The envelope reports the minimum over its window, so while the window still holds
    the best reading, a worsening focus produces no rise at all -- and the bracket that
    tells the operator to go back never fires. This is the failure a 10 s window
    produces, and it is silent.
    """
    from solareclipseworkbench.focus_metrics import RollingEnvelope

    def run(window_s):
        envelope = RollingEnvelope(window_s=window_s)
        tracker = FocusTracker()
        readings = [6.0, 4.0, 2.0, 3.0, 4.0, 5.0, 6.0]   # rack through best and out
        for index, value in enumerate(readings):
            best = envelope.add(value, now=index * 0.5)
            tracker.add(best, now=index * 0.5)
        return tracker.bracketed

    assert run(1.0) is True, "a short window must still catch the overshoot"
    assert run(30.0) is False, "the long-window failure this guards against"


def test_the_default_envelope_window_stays_short():
    from solareclipseworkbench.focus_metrics import RollingEnvelope

    assert RollingEnvelope().window_s <= 1.5


@pytest.mark.parametrize("width, expected", [
    (1.8, "at the seeing limit"),
    (2.5, "at the seeing limit"),
    (3.0, "close"),
    (4.2, "soft"),
    (9.0, "clearly defocused"),
])
def test_a_reading_grades_itself_without_any_history(width, expected):
    """The floor is set by the atmosphere, not by anything achieved this session."""
    assert grade_edge_width(width) == expected
