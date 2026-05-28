import datetime

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, Qt
from PyQt6.QtGui import QBrush, QColor

from solareclipseworkbench.gui import JobsTableModel, JobsTableColumnNames

COLUMNS = [
    JobsTableColumnNames.COUNTDOWN.value,
    JobsTableColumnNames.EXEC_TIME_LOCAL.value,
    JobsTableColumnNames.EXEC_TIME_UTC.value,
    JobsTableColumnNames.COMMAND.value,
    JobsTableColumnNames.DESCRIPTION.value,
]


def _make_model(rows):
    """Build a JobsTableModel without its heavy real __init__.

    rows: list of (exec_utc: datetime, command_cell: str). Initialises only the
    QObject machinery and the attributes mark_missed / data depend on.
    """
    model = JobsTableModel.__new__(JobsTableModel)
    QAbstractTableModel.__init__(model)
    model._missed_rows = set()
    model.execution_times_utc_as_datetime = [exec_utc for exec_utc, _ in rows]
    data = [["-", "", exec_utc, cmd, ""] for exec_utc, cmd in rows]
    model._data = pd.DataFrame(data, columns=COLUMNS)
    return model


def _utc(second):
    return datetime.datetime(2026, 8, 12, 18, 0, second, tzinfo=datetime.timezone.utc)


def test_mark_missed_sets_background_and_foreground_for_matching_row():
    model = _make_model([
        (_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)'),
        (_utc(2), 'take_picture("cam0", 1/2000, 5.6, 100)'),
    ])
    model.mark_missed("cam0", "take_picture", _utc(2))

    assert model._missed_rows == {1}
    bg = model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole)
    assert isinstance(bg, QBrush) and bg.color() == QColor("#c0392b")
    fg = model.data(model.index(1, 3), Qt.ItemDataRole.ForegroundRole)
    assert isinstance(fg, QBrush) and fg.color() == QColor("white")
    # The unmarked row carries no special colours.
    assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) is None


def test_mark_missed_time_window_tolerance():
    model = _make_model([(_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)')])
    model.mark_missed("cam0", "take_picture", _utc(0) + datetime.timedelta(seconds=1.8))
    assert model._missed_rows == {0}

    far = _make_model([(_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)')])
    far.mark_missed("cam0", "take_picture", _utc(0) + datetime.timedelta(seconds=5))
    assert far._missed_rows == set()


def test_mark_missed_disambiguates_by_camera():
    model = _make_model([
        (_utc(0), 'take_picture("cam0", 1/2000, 5.6, 100)'),
        (_utc(0), 'take_picture("cam1", 1/2000, 5.6, 100)'),
    ])
    model.mark_missed("cam1", "take_picture", _utc(0))
    assert model._missed_rows == {1}


def test_mark_missed_marks_distinct_rows_for_repeated_drops():
    model = _make_model([
        (_utc(0), 'take_burst("cam0", 1/2000, 5.6, 100, 3.0)'),
        (_utc(0), 'take_burst("cam0", 1/2000, 5.6, 100, 3.0)'),
    ])
    model.mark_missed("cam0", "take_burst", _utc(0))
    model.mark_missed("cam0", "take_burst", _utc(0))
    assert model._missed_rows == {0, 1}
