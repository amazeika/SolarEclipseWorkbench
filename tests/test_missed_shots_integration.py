"""End-to-end: a busy camera lock drops shots, and the drop flows through the
event bus into the jobs-table highlight and the CSV report.

Drops are forced deterministically by holding the per-camera lock on a *separate*
thread (the lock is reentrant, so the wrapper's own thread must differ), and the
lock-wait timeout is shrunk via monkeypatch so the test stays fast.
"""

import datetime
import threading
import time

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, Qt
from PyQt6.QtGui import QBrush, QColor

from solareclipseworkbench import camera as camera_mod
from solareclipseworkbench.camera import CameraSettings, _serialised_on_camera
from solareclipseworkbench.shot_events import BUS, ShotOutcome
from solareclipseworkbench.shot_log import ShotLog
from solareclipseworkbench.gui import JobsTableModel, JobsTableColumnNames

COMMAND = "intg_take_shot"
COLUMNS = [
    JobsTableColumnNames.COUNTDOWN.value,
    JobsTableColumnNames.EXEC_TIME_LOCAL.value,
    JobsTableColumnNames.EXEC_TIME_UTC.value,
    JobsTableColumnNames.COMMAND.value,
    JobsTableColumnNames.DESCRIPTION.value,
]


class _FakeCamera:
    def __init__(self, name="cam0"):
        self.name = name
        self._usb_lock = threading.RLock()


def _model_for(events):
    """Build a JobsTableModel with one row per event (matched by time/camera/command)."""
    model = JobsTableModel.__new__(JobsTableModel)
    QAbstractTableModel.__init__(model)
    model._missed_rows = set()
    model.execution_times_utc_as_datetime = [e.scheduled_at for e in events]
    data = [
        ["-", "", e.scheduled_at, f'{COMMAND}("{e.camera_name}", 1/2000, 5.6, 100)', ""]
        for e in events
    ]
    model._data = pd.DataFrame(data, columns=COLUMNS)
    return model


def test_drops_flow_to_highlight_and_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(camera_mod, "_MAX_LOCK_WAIT_S", 0.3)

    collected = []
    BUS.subscribe(lambda e: collected.append(e) if e.command == COMMAND else None)

    @_serialised_on_camera
    def intg_take_shot(camera, settings):
        time.sleep(0.1)  # only runs when the lock is acquired (fired path)
        return "ok"

    cam = _FakeCamera()
    settings = CameraSettings("cam0", "1/2000", "5.6", 100)

    # Hold the lock on another thread so the wrapper's timed acquire fails.
    held = threading.Event()
    release = threading.Event()

    def holder():
        cam._usb_lock.acquire()
        held.set()
        release.wait(2.0)
        cam._usb_lock.release()

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    assert held.wait(1.0)

    # Two scheduled shots arrive while the camera is busy -> both dropped.
    assert intg_take_shot(cam, settings) is None
    assert intg_take_shot(cam, settings) is None

    # Lock frees; the third shot fires.
    release.set()
    holder_thread.join(2.0)
    assert intg_take_shot(cam, settings) == "ok"

    # --- Events: 2 dropped, 1 fired ---
    outcomes = [e.outcome for e in collected]
    assert outcomes.count(ShotOutcome.DROPPED) == 2
    assert outcomes.count(ShotOutcome.FIRED) == 1

    # --- Status-bar counter proxy: dropped count per camera ---
    dropped = [e for e in collected if e.outcome == ShotOutcome.DROPPED]
    assert len(dropped) == 2  # status bar would read "Missed: 2 (cam0: 2)"

    # --- Row highlight: each dropped shot marks a distinct red row ---
    model = _model_for(collected)
    for e in dropped:
        model.mark_missed(e.camera_name, e.command, e.scheduled_at)
    assert len(model._missed_rows) == 2
    for row in model._missed_rows:
        bg = model.data(model.index(row, 0), Qt.ItemDataRole.BackgroundRole)
        assert isinstance(bg, QBrush) and bg.color() == QColor("#c0392b")

    # --- CSV report ---
    log = ShotLog()
    for e in collected:
        log.append(e)
    rows = _read_csv(log.write_csv(tmp_path / "intg.shots.csv"))

    assert len(rows) == 1 + 3  # header + 3 shots
    dropped_rows = [r for r in rows[1:] if r[3] == "dropped"]
    fired_rows = [r for r in rows[1:] if r[3] == "fired"]
    assert len(dropped_rows) == 2 and len(fired_rows) == 1
    # Dropped shots never ran: drift is the 0 sentinel.
    assert all(r[2] == "0" for r in dropped_rows)
    # Fired shot ran ~0.1 s, so its drift is clearly positive.
    assert int(fired_rows[0][2]) >= 50


def _read_csv(path):
    import csv
    with open(path, newline="") as handle:
        return list(csv.reader(handle))
