"""Unit tests for `_find_drive_mode_choice` (Canon burst drive-mode resolution).

These are pure-logic tests: the gphoto2 widget is faked as a plain list of
choice strings and the three `gp` calls the helper makes are monkeypatched to
read from it. No camera or libgphoto2 backend is required.
"""

import pytest

from solareclipseworkbench import camera as cam
from solareclipseworkbench.camera import _find_drive_mode_choice


@pytest.fixture
def fake_widget(monkeypatch):
    """Return a factory that turns a list of choice strings into a fake widget.

    Patches `check_result` to identity and the choice-introspection calls to
    read from the list, so `_find_drive_mode_choice` can run unmodified.
    """
    monkeypatch.setattr(cam.gp, "check_result", lambda x: x)
    monkeypatch.setattr(cam.gp, "gp_widget_count_choices", lambda w: len(w))
    monkeypatch.setattr(cam.gp, "gp_widget_get_choice", lambda w, i: w[i])
    return lambda choices: list(choices)


# The exact drivemode choices a real Canon EOS 70D reports.
_70D_CHOICES = [
    "Single",
    "Continuous high speed",
    "Continuous low speed",
    "Single silent",
    "Continuous silent",
    "Timer 10 sec",
    "Timer 2 sec",
]


def test_70d_continuous_prefers_high_speed(fake_widget):
    widget = fake_widget(_70D_CHOICES)
    assert _find_drive_mode_choice(widget, want_continuous=True) == "Continuous high speed"


def test_70d_single_picks_plain_single_over_silent(fake_widget):
    widget = fake_widget(_70D_CHOICES)
    assert _find_drive_mode_choice(widget, want_continuous=False) == "Single"


def test_continuous_without_high_falls_back_to_first_continuous(fake_widget):
    widget = fake_widget(["Single", "Continuous", "Continuous silent"])
    assert _find_drive_mode_choice(widget, want_continuous=True) == "Continuous"


def test_no_continuous_choice_returns_none(fake_widget):
    widget = fake_widget(["Single", "Timer 10 sec"])
    assert _find_drive_mode_choice(widget, want_continuous=True) is None


def test_no_single_choice_returns_none(fake_widget):
    widget = fake_widget(["Continuous high speed", "Timer 2 sec"])
    assert _find_drive_mode_choice(widget, want_continuous=False) is None


def test_case_insensitive_matching(fake_widget):
    widget = fake_widget(["SINGLE", "CONTINUOUS HIGH SPEED"])
    assert _find_drive_mode_choice(widget, want_continuous=True) == "CONTINUOUS HIGH SPEED"
    assert _find_drive_mode_choice(widget, want_continuous=False) == "SINGLE"
