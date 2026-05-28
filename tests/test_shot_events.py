import threading
from datetime import datetime, timezone

from solareclipseworkbench.shot_events import (
    BUS,
    ShotEvent,
    ShotEventBus,
    ShotOutcome,
)


def _event(outcome=ShotOutcome.FIRED, command="take_picture"):
    now = datetime.now(timezone.utc)
    return ShotEvent(
        camera_name="cam0",
        command=command,
        scheduled_at=now,
        fired_at=now,
        outcome=outcome,
    )


def test_publish_invokes_subscribers_in_order():
    bus = ShotEventBus()
    calls = []
    bus.subscribe(lambda e: calls.append(("a", e)))
    bus.subscribe(lambda e: calls.append(("b", e)))

    evt = _event()
    bus.publish(evt)

    assert [tag for tag, _ in calls] == ["a", "b"]
    assert all(e is evt for _, e in calls)


def test_subscriber_raising_does_not_block_others():
    bus = ShotEventBus()
    seen = []

    def boom(_):
        raise RuntimeError("subscriber failure")

    bus.subscribe(boom)
    bus.subscribe(lambda e: seen.append(e))

    # Must not raise even though the first subscriber throws.
    bus.publish(_event())

    assert len(seen) == 1


def test_module_bus_is_a_shot_event_bus():
    assert isinstance(BUS, ShotEventBus)


def test_concurrent_subscribe_and_publish_are_safe():
    # Bounded on every axis so the subscriber list and delivery count stay
    # small: a fixed, tiny number of subscribes interleaved with a fixed number
    # of publishes. The point is to exercise the lock under contention, not to
    # stress throughput -- an unbounded subscribe loop here would blow up memory
    # (each publish delivers to every subscriber).
    bus = ShotEventBus()
    counter = [0]
    counter_lock = threading.Lock()

    def subscriber(_evt):
        with counter_lock:
            counter[0] += 1

    SUBSCRIBES = 8
    PUBLISHES = 50

    def subscribe_worker():
        for _ in range(SUBSCRIBES):
            bus.subscribe(subscriber)

    def publish_worker():
        for _ in range(PUBLISHES):
            bus.publish(_event())

    threads = [
        threading.Thread(target=subscribe_worker),
        threading.Thread(target=publish_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # After everything settles, a final publish reaches exactly the subscribers
    # registered (no lost or duplicated subscriptions, no exception escaped).
    before = counter[0]
    bus.publish(_event())
    assert counter[0] - before == SUBSCRIBES


def test_dropped_event_carries_equal_timestamps():
    evt = _event(outcome=ShotOutcome.DROPPED)
    assert evt.scheduled_at == evt.fired_at
    assert evt.outcome == "dropped"
