import csv
import datetime

from solareclipseworkbench import shot_log
from solareclipseworkbench.shot_events import ShotEvent, ShotOutcome


def _event(outcome=ShotOutcome.FIRED, drift_s=0.0, command="take_picture", detail=""):
    scheduled = datetime.datetime(2026, 8, 12, 18, 0, 0, tzinfo=datetime.timezone.utc)
    fired = scheduled + datetime.timedelta(seconds=drift_s)
    return ShotEvent(
        camera_name="cam0",
        command=command,
        scheduled_at=scheduled,
        fired_at=fired,
        outcome=outcome,
        description="1/2000, 5.6, 100",
        detail=detail,
    )


def _read(path):
    with open(path, newline="") as handle:
        return list(csv.reader(handle))


def test_write_csv_schema_and_drift(tmp_path):
    log = shot_log.ShotLog()
    log.append(_event(ShotOutcome.FIRED, drift_s=0.25))
    log.append(_event(ShotOutcome.DROPPED, drift_s=0.0))
    log.append(_event(ShotOutcome.FAILED, drift_s=1.5, detail="ValueError: boom"))

    out = log.write_csv(tmp_path / "run.shots.csv")
    rows = _read(out)

    assert rows[0] == [
        "scheduled_at", "fired_at", "drift_ms", "outcome",
        "camera", "command", "description", "detail",
    ]
    assert len(rows) == 4
    # drift_ms column (index 2) and outcome (index 3)
    assert rows[1][2] == "250" and rows[1][3] == "fired"
    assert rows[2][2] == "0" and rows[2][3] == "dropped"
    assert rows[3][2] == "1500" and rows[3][3] == "failed"
    assert rows[3][7] == "ValueError: boom"


def test_write_csv_empty_is_header_only(tmp_path):
    out = shot_log.ShotLog().write_csv(tmp_path / "empty.shots.csv")
    rows = _read(out)
    assert len(rows) == 1
    assert rows[0][0] == "scheduled_at"


def test_set_run_basename_and_write_report(tmp_path):
    shot_log.LOG.append(_event(ShotOutcome.DROPPED, command="take_burst"))
    shot_log.set_run_basename(str(tmp_path / "session"))
    out = shot_log.write_report()

    assert out == tmp_path / "session.shots.csv"
    assert out.exists()
    rows = _read(out)
    assert rows[0][0] == "scheduled_at"
    # Our appended event is present (global LOG may hold others from the bus).
    assert any(r[3] == "dropped" and r[5] == "take_burst" for r in rows[1:])
