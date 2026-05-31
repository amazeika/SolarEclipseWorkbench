"""The missed-shots indicator counts both DROPPED and FAILED outcomes.

A DROPPED shot never fired (USB still busy); a FAILED shot was attempted but
errored (e.g. -110 I/O in progress). Both mean the planned frame was not
captured, so SolarEclipseView._on_shot_event must mark the row and bump the
counter for either outcome -- and ignore FIRED.

The view is built via __new__ so the heavy real __init__ (and a QApplication)
is not needed; only the handful of attributes _on_shot_event touches are set,
with a duck-typed stub standing in for the QLabel.
"""

import datetime

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel

from solareclipseworkbench.gui import SolarEclipseView, JobsTableModel, JobsTableColumnNames
from solareclipseworkbench.shot_events import ShotEvent, ShotOutcome

COLUMNS = [
    JobsTableColumnNames.COUNTDOWN.value,
    JobsTableColumnNames.EXEC_TIME_LOCAL.value,
    JobsTableColumnNames.EXEC_TIME_UTC.value,
    JobsTableColumnNames.COMMAND.value,
    JobsTableColumnNames.DESCRIPTION.value,
]


def _utc(second):
    return datetime.datetime(2026, 8, 12, 18, 0, second, tzinfo=datetime.timezone.utc)


def _model_with_row(exec_utc, command_cell):
    model = JobsTableModel.__new__(JobsTableModel)
    QAbstractTableModel.__init__(model)
    model._missed_rows = set()
    model.execution_times_utc_as_datetime = [exec_utc]
    model._data = pd.DataFrame(
        [["-", "", exec_utc, command_cell, ""]], columns=COLUMNS
    )
    return model


class _LabelStub:
    def setText(self, text):
        self.text = text

    def setStyleSheet(self, sheet):
        self.sheet = sheet


class _TableStub:
    def __init__(self, model):
        self._model = model

    def model(self):
        return self._model


def _view_with(model):
    view = SolarEclipseView.__new__(SolarEclipseView)
    view._missed_counts = {}
    view._missed_label = _LabelStub()
    view.jobs_table = _TableStub(model)
    return view


def _event(outcome):
    return ShotEvent(
        camera_name="cam0",
        command="take_picture",
        scheduled_at=_utc(0),
        fired_at=_utc(0),
        outcome=outcome,
        description='take_picture("cam0", 1/2000, 5.6, 100)',
    )


def test_failed_shot_counts_as_missed():
    model = _model_with_row(_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)')
    view = _view_with(model)

    view._on_shot_event(_event(ShotOutcome.FAILED))

    assert model._missed_rows == {0}
    assert view._missed_counts == {"cam0": 1}
    assert view._missed_label.text == "Missed: 1 (cam0: 1)"


def test_dropped_shot_counts_as_missed():
    model = _model_with_row(_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)')
    view = _view_with(model)

    view._on_shot_event(_event(ShotOutcome.DROPPED))

    assert model._missed_rows == {0}
    assert view._missed_counts == {"cam0": 1}


def test_fired_shot_is_not_missed():
    model = _model_with_row(_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)')
    view = _view_with(model)

    view._on_shot_event(_event(ShotOutcome.FIRED))

    assert model._missed_rows == set()
    assert view._missed_counts == {}
