"""Thread-safe pub/sub for camera shot outcomes.

This module is deliberately free of any GUI (PyQt/PySide) dependency so that
``camera.py`` can publish events while remaining importable in headless / CLI
contexts. The GUI subscribes via a Qt bridge (see ``gui.py``).

Subscriber contract
-------------------
``BUS.publish`` runs **synchronously on the calling thread** -- which, for shot
events, is the APScheduler/camera thread that must fire the next shot on time.
Subscribers MUST therefore return almost immediately: no blocking I/O, no locks
held across slow work, no synchronous capture-adjacent calls. Hand heavy work
off to another thread (the Qt bridge does this by emitting a queued signal). A
slow synchronous subscriber would run on the camera thread and could push a
later shot past its drop threshold -- the instrumentation would create the very
misses it is meant to report.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

LOGGER = logging.getLogger(__name__)


class ShotOutcome(str, Enum):
    """Outcome of a single scheduled capture command."""

    FIRED = "fired"
    DROPPED = "dropped"
    FAILED = "failed"


@dataclass(frozen=True)
class ShotEvent:
    """A single shot outcome, published once per scheduled capture call."""

    camera_name: str
    command: str
    scheduled_at: datetime
    fired_at: datetime
    outcome: ShotOutcome
    description: str = ""
    detail: str = ""


class ShotEventBus:
    """Thread-safe publish/subscribe for :class:`ShotEvent`.

    Subscribers are invoked in subscription order. The subscriber list is
    iterated under a lock, but each callback is invoked *outside* the lock so a
    callback that re-publishes cannot deadlock, and a callback that raises is
    caught and logged so it cannot break publishing or the publishing thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list = []

    def subscribe(self, callback) -> None:
        """Register ``callback`` to receive every subsequently published event.

        ``callback`` is invoked on the publishing thread and must return almost
        immediately -- no blocking I/O or slow work. See the module docstring's
        subscriber contract.
        """
        with self._lock:
            self._subscribers.append(callback)

    def publish(self, event: ShotEvent) -> None:
        """Deliver ``event`` to all subscribers. Never raises."""
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                LOGGER.exception("shot-event subscriber raised; continuing")


BUS = ShotEventBus()
