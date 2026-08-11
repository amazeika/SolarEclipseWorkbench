"""The filter-off lockout: live view must not run while the sun is unfiltered.

The window is C2-25s .. C3+25s, five seconds either side of the C2-20s / C3+20s
filter handover. It is deliberately *not* extended to C1 and C4 -- the filter is on
through both, and the schedule guard covers their tightly spaced contact shots.
"""

import datetime
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.camera import VirtualCamera
from solareclipseworkbench.gui import (
    LiveViewWindow,
    live_view_locked_out,
)

C2 = datetime.datetime(2026, 8, 12, 18, 30, 0, tzinfo=datetime.timezone.utc)
C3 = datetime.datetime(2026, 8, 12, 18, 31, 35, tzinfo=datetime.timezone.utc)
C1 = datetime.datetime(2026, 8, 12, 17, 32, 0, tzinfo=datetime.timezone.utc)


class _Moment:
    def __init__(self, time_utc):
        self.time_utc = time_utc


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def _patched_thread():
    """Patch LiveViewThread with a stand-in whose state attributes read as idle.

    A bare MagicMock returns a MagicMock for every attribute, which the status label
    would read as "held" and try to format as a number.
    """
    patcher = patch("solareclipseworkbench.gui.LiveViewThread")
    thread_cls = patcher.start()
    thread_cls.return_value.held_seconds = None
    thread_cls.return_value.zoom_error = None
    thread_cls.return_value.zoom_level = 1
    thread_cls.return_value.zoom_engaged = False

    class _Ctx:
        def __enter__(self):
            return thread_cls

        def __exit__(self, *exc):
            patcher.stop()
            return False

    return _Ctx()


@pytest.mark.parametrize("offset_s, expected", [
    (-26, False),   # just outside the lead
    (-25, True),    # the lead boundary itself
    (-20, True),    # the filter actually comes off here
    (0, True),
])
def test_the_lockout_opens_25_seconds_before_second_contact(offset_s, expected):
    now = C2 + datetime.timedelta(seconds=offset_s)

    assert live_view_locked_out(now, _Moment(C2), _Moment(C3)) is expected


@pytest.mark.parametrize("offset_s, expected", [
    (0, True),
    (20, True),     # the filter goes back on here
    (25, True),     # the trail boundary itself
    (26, False),    # just outside the trail
])
def test_the_lockout_closes_25_seconds_after_third_contact(offset_s, expected):
    now = C3 + datetime.timedelta(seconds=offset_s)

    assert live_view_locked_out(now, _Moment(C2), _Moment(C3)) is expected


def test_totality_itself_is_locked_out():
    mid = C2 + (C3 - C2) / 2

    assert live_view_locked_out(mid, _Moment(C2), _Moment(C3)) is True


def test_first_contact_is_not_locked_out():
    """C1 keeps its filter on, and it is when the operator checks framing and focus."""
    for offset_s in (-5, 0, 5):
        now = C1 + datetime.timedelta(seconds=offset_s)

        assert live_view_locked_out(now, _Moment(C2), _Moment(C3)) is False


def test_a_partial_eclipse_never_locks_out():
    """A partial has no C2 or C3 and never loses its filter."""
    assert live_view_locked_out(C1, None, None) is False
    assert live_view_locked_out(C1, _Moment(C2), None) is False


def test_a_window_opened_inside_the_lockout_never_grabs_a_frame(_qapp):
    """The race this closes: one frame is enough to put the mirror up."""
    with _patched_thread() as thread_cls:
        window = LiveViewWindow(VirtualCamera(), locked_out=True)
        try:
            assert thread_cls.call_args.kwargs["start_paused"] is True
            # Constructed paused, then confirmed paused rather than resumed.
            assert thread_cls.return_value.resume.call_count == 0
        finally:
            window.close()


def test_the_toggle_cannot_re_enable_live_view_during_the_lockout(_qapp):
    with patch("solareclipseworkbench.gui.LiveViewThread"):
        window = LiveViewWindow(VirtualCamera(), locked_out=True)
        try:
            window._apply_state()
            assert window._toggle_btn.isEnabled() is False

            # A disabled button still fires on a programmatic click.
            window._toggle_btn.click()
            window._on_toggle()

            assert window._user_enabled is True
            assert "Locked out" in window._status_label.text()
        finally:
            window.close()


def test_leaving_the_lockout_resumes_without_operator_action(_qapp):
    with _patched_thread() as thread_cls:
        window = LiveViewWindow(VirtualCamera(), locked_out=True)
        try:
            thread_cls.return_value.resume.reset_mock()

            window.set_locked_out(False)

            assert thread_cls.return_value.resume.called
            assert window._toggle_btn.isEnabled() is True
            assert "Active" in window._status_label.text()
        finally:
            window.close()


def test_closing_the_window_stops_the_thread_and_announces_it(_qapp):
    with _patched_thread() as thread_cls:
        window = LiveViewWindow(VirtualCamera())
        seen = []
        window.closed.connect(lambda: seen.append(True))

        window.close()

        assert thread_cls.return_value.stop.called
        assert seen == [True], "the controller was never told the window went away"
