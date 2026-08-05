"""Scheduler misfires must reach the shot report.

A shot can die in two places. _serialised_on_camera reports the one it sees -- the USB
lock still busy -- but a job APScheduler cannot start within its grace time is skipped
before any camera code runs. Without this listener such a shot leaves no CSV row, so a
run can report every shot as fired while frames go missing.
"""

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent

from solareclipseworkbench import utils
from solareclipseworkbench.camera import CameraSettings
from solareclipseworkbench.shot_events import BUS, ShotOutcome

SCHEDULED_AT = datetime.datetime(2026, 8, 12, 17, 33, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def published():
    events = []
    BUS.subscribe(events.append)
    yield events


@pytest.fixture(autouse=True)
def _clear_meta():
    utils._JOB_META.clear()
    yield
    utils._JOB_META.clear()


def _missed(job_id="job-1"):
    return JobExecutionEvent(EVENT_JOB_MISSED, job_id, "default", SCHEDULED_AT)


def test_a_misfire_is_reported_as_a_dropped_shot(published):
    utils._on_job_missed(_missed())

    assert len(published) == 1
    event = published[0]
    assert event.outcome is ShotOutcome.DROPPED
    assert event.detail == "apscheduler misfire"
    assert event.scheduled_at == SCHEDULED_AT


def test_the_report_says_which_shot_went_missing(published):
    utils._JOB_META["job-1"] = ("Canon EOS 80D", "take_picture", "1/2500, 4.7, 400")

    utils._on_job_missed(_missed())

    event = published[0]
    assert event.camera_name == "Canon EOS 80D"
    assert event.command == "take_picture"
    assert event.description == "1/2500, 4.7, 400"


def test_an_unrecognised_job_is_still_reported(published):
    """Losing the description is survivable; losing the row is not."""
    utils._on_job_missed(_missed(job_id="never-registered"))

    assert len(published) == 1
    assert published[0].outcome is ShotOutcome.DROPPED
    assert published[0].command == "unknown"


def test_drift_is_zero_because_nothing_ever_ran(published):
    utils._on_job_missed(_missed())

    event = published[0]
    assert event.fired_at == event.scheduled_at


def test_the_listener_is_registered_when_the_scheduler_starts():
    scheduler = utils.start_scheduler()
    try:
        registered = [callback for callback, mask in scheduler._listeners
                      if mask & EVENT_JOB_MISSED]
        assert utils._on_job_missed in registered
    finally:
        scheduler.shutdown()


def test_scheduling_a_shot_records_what_it_was_end_to_end(published):
    """Metadata is captured when the job is added, because a one-shot job is gone
    from the store by the time its misfire fires."""
    scheduler = utils.start_scheduler()
    try:
        c1 = type("_Moment", (), {"time_utc": SCHEDULED_AT})()
        utils.schedule_command(
            scheduler=scheduler,
            reference_moments={"C1": c1},
            cmd_str='take_picture, C1, +, 1:00:00.0, Canon EOS 80D, 1/2500, 4.7, 400, "Partial C1-C2 #1"',
            cameras={"Canon EOS 80D": object()},
            controller=None,
            reference_moment_for_simulation=None,
            simulated_start=None,
        )

        assert len(utils._JOB_META) == 1
        job_id, meta = next(iter(utils._JOB_META.items()))
        assert meta == ("Canon EOS 80D", "take_picture", "Partial C1-C2 #1")

        # And that metadata is what a misfire on this job would report.
        utils._on_job_missed(_missed(job_id=job_id))
        assert published[-1].camera_name == "Canon EOS 80D"
        assert published[-1].description == "Partial C1-C2 #1"
    finally:
        scheduler.shutdown()
