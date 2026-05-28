"""Post-run CSV report of shot outcomes.

A module-level :data:`LOG` subscribes itself to the Qt-free shot-event bus, so
recording works regardless of whether the GUI is running. The report is written
to ``<run-stem>.shots.csv`` (next to the run log) at app close
(:meth:`gui.SolarEclipseView.closeEvent`) and, as a backstop for abnormal exits,
via an ``atexit`` handler.
"""

import atexit
import csv
import logging
import threading
from pathlib import Path

from solareclipseworkbench.shot_events import BUS, ShotEvent

LOGGER = logging.getLogger(__name__)

_CSV_FIELDS = [
    "scheduled_at",
    "fired_at",
    "drift_ms",
    "outcome",
    "camera",
    "command",
    "description",
    "detail",
]


class ShotLog:
    """Thread-safe accumulator of shot events with CSV export."""

    def __init__(self):
        self._events: list[ShotEvent] = []
        self._lock = threading.Lock()

    def append(self, event: ShotEvent) -> None:
        with self._lock:
            self._events.append(event)

    def write_csv(self, path) -> Path:
        """Write one row per recorded shot to ``path`` (header always written)."""
        path = Path(path)
        with self._lock:
            events = list(self._events)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_CSV_FIELDS)
            for event in events:
                drift_ms = (event.fired_at - event.scheduled_at).total_seconds() * 1000
                writer.writerow([
                    event.scheduled_at.isoformat(),
                    event.fired_at.isoformat(),
                    f"{drift_ms:.0f}",
                    event.outcome.value,
                    event.camera_name,
                    event.command,
                    event.description,
                    event.detail,
                ])
        return path


LOG = ShotLog()
BUS.subscribe(LOG.append)

_run_csv_path: Path | None = None


def set_run_basename(stem: str) -> None:
    """Configure the report path as ``<stem>.shots.csv`` for this run."""
    global _run_csv_path
    _run_csv_path = Path(f"{stem}.shots.csv")


def write_report() -> Path | None:
    """Write the report if a run basename was configured; never raises."""
    if _run_csv_path is None:
        return None
    try:
        LOG.write_csv(_run_csv_path)
        LOGGER.info("Wrote shot report to %s", _run_csv_path)
        return _run_csv_path
    except Exception:
        LOGGER.exception("Failed to write shot report to %s", _run_csv_path)
        return None


atexit.register(write_report)
