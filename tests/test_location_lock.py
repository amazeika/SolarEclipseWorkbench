"""When a script is loaded it owns the observing coordinates.

SolarEclipseController.update() must, for a LocationPopup change:
  * always accept the GPS time offset (orthogonal to coordinates), and
  * while script_loaded is True, NOT overwrite the model coordinates
    (the schedule was already built from the script's header location);
  * while script_loaded is False, apply the coordinates as before.

Both controller and pop-up are built via __new__ so no QApplication/real
widgets are needed; QMessageBox is stubbed so the locked path doesn't try to
show a dialog.
"""

import datetime

import pytest

from solareclipseworkbench import gui
from solareclipseworkbench.gui import SolarEclipseController, LocationPopup


class _Edit:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _LocationWidget:
    def __init__(self):
        self.longitude_edit = _Edit("1.5")
        self.latitude_edit = _Edit("2.5")
        self.altitude_edit = _Edit("100")
        self.gps_time_offset = datetime.timedelta(seconds=7)


class _Model:
    def __init__(self):
        self.longitude = self.latitude = self.altitude = None
        self.gps_time_offset = datetime.timedelta(0)
        self.set_position_calls = []

    def set_position(self, longitude, latitude, altitude):
        self.set_position_calls.append((longitude, latitude, altitude))
        self.longitude, self.latitude, self.altitude = longitude, latitude, altitude


class _Label:
    def setText(self, _):
        pass


class _Viz:
    def set_location(self, *_):
        pass


class _View:
    def __init__(self):
        self.longitude_label = _Label()
        self.latitude_label = _Label()
        self.altitude_label = _Label()
        self.eclipse_visualization = _Viz()


def _popup():
    p = LocationPopup.__new__(LocationPopup)
    p.location_widget = _LocationWidget()
    return p


def _controller(script_loaded):
    c = SolarEclipseController.__new__(SolarEclipseController)
    c.model = _Model()
    c.view = _View()
    c.script_loaded = script_loaded
    return c


def test_coordinates_locked_while_script_loaded(monkeypatch):
    shown = []
    monkeypatch.setattr(gui.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))
    c = _controller(script_loaded=True)

    c.update(_popup())

    # Coordinates were NOT applied...
    assert c.model.set_position_calls == []
    assert c.model.longitude is None
    # ...but the GPS time offset still was, and the user was told why.
    assert c.model.gps_time_offset == datetime.timedelta(seconds=7)
    assert shown, "expected a 'locked to script' message"


def test_coordinates_applied_when_no_script_loaded(monkeypatch):
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *a, **k: None)
    c = _controller(script_loaded=False)

    c.update(_popup())

    assert c.model.set_position_calls == [(1.5, 2.5, 100.0)]
    assert c.model.gps_time_offset == datetime.timedelta(seconds=7)
