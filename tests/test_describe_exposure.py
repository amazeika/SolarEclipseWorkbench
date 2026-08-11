"""Exposure summary for a review capture.

A captured frame can be black because the settings are wrong, or black because they
are right and there is nothing bright in front of the camera -- a solar exposure
indoors, for instance. Those look identical on screen and mean opposite things, so the
numbers have to be reported rather than left to the eye.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.gui import describe_exposure


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def _disc(peak=200.0, background=4.0, radius=90, size=(400, 600)):
    ys, xs = np.mgrid[0:size[0], 0:size[1]]
    distance = np.sqrt((xs - size[1] / 2) ** 2 + (ys - size[0] / 2) ** 2)
    return np.where(distance < radius, peak, background)


def test_a_solar_exposure_indoors_is_called_out_as_empty_not_broken(_qapp):
    """1/2500 at ISO 400 indoors is genuinely black, and that is not a fault."""
    summary = describe_exposure(np.full((400, 600), 3.0))

    assert "nothing registered" in summary
    assert "peak" in summary, "the raw numbers must be shown alongside the verdict"


def test_a_well_exposed_disc_is_accepted(_qapp):
    summary = describe_exposure(_disc())

    assert "usable" in summary


def test_a_blown_disc_says_what_to_change(_qapp):
    summary = describe_exposure(_disc(peak=255.0))

    assert "blown highlights" in summary
    assert "shorten" in summary or "ISO" in summary


def test_a_dim_disc_is_distinguished_from_an_empty_frame(_qapp):
    """Something is there, but nowhere near what a filtered sun should give."""
    summary = describe_exposure(_disc(peak=70.0))

    assert "dim" in summary
    assert "nothing registered" not in summary


def test_a_bright_speck_is_questioned(_qapp):
    """A stray highlight is not the sun, and would otherwise pass as exposed."""
    summary = describe_exposure(_disc(peak=240.0, radius=3))

    assert "in frame" in summary


def test_the_numbers_are_always_reported(_qapp):
    summary = describe_exposure(_disc())

    for field in ("peak", "mean", "lit", "blown"):
        assert field in summary
