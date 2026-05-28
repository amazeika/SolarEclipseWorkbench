---
status: in-progress
issue: 1
pr: 2
completed:
  - "Phase 1: ShotEventBus"
---

# Missed-Shots Indicator — Design Document

> **Created:** May 2026

Adds live UI feedback and a post-run CSV report when scheduled shots are silently
dropped because the camera could not keep up. The drop behaviour itself is unchanged —
this feature only surfaces what is already happening so the user learns about missed
shots during the run instead of by trawling the log file afterwards.

Related: [`camera.py`](../../src/solareclipseworkbench/camera.py) (`_serialised_on_camera`),
[`gui.py`](../../src/solareclipseworkbench/gui.py) (`SolarEclipseView`, `JobsTableModel`).

---

## 1. Motivation

### Current state

`SolarEclipseWorkbench` schedules each capture command via APScheduler, then serialises
USB access through a per-camera lock decorator (`_serialised_on_camera`,
[camera.py:557](../../src/solareclipseworkbench/camera.py#L557)). If the lock cannot be
acquired within `_MAX_LOCK_WAIT_S` (1.5 s, [camera.py:554](../../src/solareclipseworkbench/camera.py#L554)),
the shot is **silently dropped** to preserve timing for later commands — the only signal
is a `logging.warning` line:

```python
acquired = camera._usb_lock.acquire(timeout=_MAX_LOCK_WAIT_S)
if not acquired:
    logging.warning('%s: dropped — camera was still busy after %.1fs ...', ...)
    return
```

This is the correct timing decision (a late shot skews the whole sequence), but there is
**no GUI feedback**:

- `JobsTableModel` ([gui.py:2537](../../src/solareclipseworkbench/gui.py#L2537)) tracks
  `next_run_time` only — never actual fire time or "missed" status.
- No APScheduler `JOB_MISSED` / `JOB_EXECUTED` listeners are registered.
- `SolarEclipseView` ([gui.py:275](../../src/solareclipseworkbench/gui.py#L275), a
  `QMainWindow`) does not use its status bar.
- There is no post-run report.

### Goal

Three additions, with no behavioural change to the timing decision:

1. **Live counter** in the status bar — `Missed: N` per camera, updated in real time.
2. **Row highlight** in the jobs table — dropped-shot rows turn red.
3. **Post-run CSV report** — one row per scheduled shot
   (`scheduled_at`, `fired_at`, `drift_ms`, `outcome`, camera, command, description, detail)
   written next to the run log on scheduler shutdown / app close.

**Non-goal:** changing the drop behaviour. The 1.5 s threshold and silent skip stay.

### Use cases

- Tight C2/C3 sequences (18-shot corona at ~2 s spacing, `take_hdr` 15 shots in ~25 s,
  back-to-back `take_burst` for Baily's beads) on slower bodies (e.g. Canon EOS 1100D,
  ~1.0–1.5 s inter-shot floor) will silently drop many shots.
- The Aug 12 2026 eclipse is a one-shot event — the user needs to see keep-up failures
  *live* (so they can adjust) and have a *machine-readable record* afterward.

### Concepts

| Term | Definition |
|------|------------|
| Drop | A scheduled shot skipped because the USB lock was busy past `_MAX_LOCK_WAIT_S`. |
| Drift | `fired_at - scheduled_at` — wait-plus-execute latency; "did this shot run late?". |
| Shot outcome | One of `fired`, `dropped`, `failed`. |

---

## 2. Design

APScheduler fires each job on its own thread, so camera code runs **off the GUI thread**.
The signal path must be thread-safe and must not pull Qt into `camera.py` (the headless
CLI imports `camera.py` and must work without PyQt).

**Approach: a Qt-free module-level event bus + a Qt bridge in the GUI.**

```
 scheduler thread                          GUI thread
┌──────────────────┐   BUS.publish   ┌──────────────────┐  pyqtSignal   ┌───────────────────┐
│ _serialised_on_  │ ──────────────▶ │ ShotEventBus     │ ────────────▶ │ _ShotEventBridge  │
│ camera (wrapper) │   ShotEvent     │ (threading.Lock) │  (emit)       │  .event(object)   │
└──────────────────┘                 └──────────────────┘               └─────────┬─────────┘
                                                                                   │ queued slot
                                                              ┌────────────────────┼────────────────────┐
                                                              ▼                    ▼                    ▼
                                                     status-bar counter    JobsTableModel        ShotLog
                                                     (Missed: N)           .mark_missed()        (CSV at close)
```

### Components

- **`shot_events.py`** (new, Qt-free, ~50 lines): `ShotOutcome` enum, `ShotEvent`
  dataclass, `ShotEventBus` with `subscribe`/`publish`, and a module-level `BUS`.
  Subscriber list guarded by a `threading.Lock`; each callback invoked **outside** the
  lock (so a subscriber that re-publishes can't deadlock) and wrapped in try/except (so
  one bad subscriber can't break publishing or the camera thread).

  ```python
  class ShotOutcome(str, Enum):
      FIRED = "fired"; DROPPED = "dropped"; FAILED = "failed"

  @dataclass(frozen=True)
  class ShotEvent:
      camera_name: str
      command: str            # "take_picture" | "take_burst" | "take_hdr" | ...
      scheduled_at: datetime  # UTC — lock-acquire entry time
      fired_at: datetime      # UTC — equals scheduled_at when DROPPED
      outcome: ShotOutcome
      description: str = ""
      detail: str = ""        # free-form, e.g. exception message
  ```

- **`camera.py`**: `_serialised_on_camera.wrapper` publishes a `ShotEvent` on the drop
  branch (`DROPPED`), on success (`FIRED`), and on exception (`FAILED`, then re-raises).
  A private `_describe_args(func_name, args, kwargs) -> str` formats `CameraSettings`
  highlights (shutter / aperture / ISO) for capture commands. No Qt import.

- **`gui.py`**: a single `_ShotEventBridge(QObject)` with `event = pyqtSignal(object)`
  subscribes its `emit` to `BUS`; it is held on `SolarEclipseView` for GUI-thread
  affinity. Its slot updates the status bar, marks the table row, and appends to `ShotLog`.

- **`ShotLog`**: in-memory list of events (lock-guarded) with `write_csv(path)`. Written
  at app close / scheduler shutdown.

### Subscriber contract (performance-critical)

`BUS.publish` runs **synchronously on the scheduler/camera thread** — the same thread that
must fire the next shot on time. Per-shot overhead is therefore deliberately tiny
(`datetime.now()` ×1–2, one frozen-dataclass alloc, a brief lock, one `emit`), tens of
microseconds against a ~1–1.5 s capture. This stays negligible **only while every
subscriber is cheap and non-blocking**.

The GUI subscriber upholds this: `_ShotEventBridge._on_bus_event` does nothing but
`self.event.emit(evt)`, and because the bridge has GUI-thread affinity while `emit` is
called from the scheduler thread, Qt uses a **queued connection** — `emit` returns
immediately and the real work (status bar, table repaint, `ShotLog.append`) happens later
on the GUI thread.

**Contract for future subscribers:** a `BUS` subscriber must return almost immediately —
no I/O, no locks held across slow work, no synchronous capture-adjacent calls. Anything
heavier must hand off to another thread (as the Qt bridge does). Document this directly in
`shot_events.py`'s `subscribe` docstring; a slow synchronous subscriber would run on the
camera thread and could push a subsequent shot past `_MAX_LOCK_WAIT_S`, causing a drop —
i.e. the instrumentation would *create* the very misses it reports.

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cross-thread signalling | Qt-free bus + bridge | Keeps `camera.py` headless-importable; avoids calling Qt widgets from scheduler threads. |
| Not reusing `Observable` | Separate `ShotEventBus` | `Observable` already drives `JobsTableModel` countdowns; overloading it couples unrelated concerns. |
| `scheduled_at` source | Lock-acquire entry time | APScheduler doesn't pass scheduled run time to the job by default; entry time is the closest in-process proxy and yields the drift the user cares about. |
| HDR/burst granularity | One event per call | Per-sub-shot reporting needs hooks inside the HDR/burst loop — deferred (see Open Questions). |

### Event → outcome mapping

Every scheduled capture goes through `_serialised_on_camera`'s `wrapper`, which stamps
`scheduled_at = now()` on entry (the moment the job thread reaches the lock) and then
takes exactly one of three paths. Each path publishes **exactly one** `ShotEvent`, so the
number of events always equals the number of scheduled shots — that 1:1 guarantee is what
lets the CSV report claim "one row per scheduled shot".

The three paths:

1. **Lock busy → `dropped`.** The previous shot still holds the USB lock after
   `_MAX_LOCK_WAIT_S`. The wrapped capture function never runs, so there is no real fire
   moment — we set `fired_at = scheduled_at` (drift = 0) as a sentinel meaning "did not
   execute". The status bar and red row come from this branch.
2. **Capture succeeds → `fired`.** The lock was acquired and the capture function returned
   normally. `fired_at = now()` is stamped *after* it returns, so
   `drift = fired_at - scheduled_at` captures lock-wait + execution time — i.e. "how late
   did this shot actually run?".
3. **Capture raises → `failed`.** The lock was acquired but the capture function threw
   (e.g. a gphoto2 `-110` I/O error). We stamp `fired_at = now()`, record the exception in
   `detail`, publish, then **re-raise** so existing error handling is unchanged.

| Path | Outcome | `fired_at` | `drift_ms` meaning | `detail` |
| ---- | ------- | ---------- | ------------------ | -------- |
| lock not acquired within `_MAX_LOCK_WAIT_S` | `dropped` | `= scheduled_at` | always 0 (shot never ran) | empty |
| capture function returns | `fired` | timestamp after it returns | lock-wait + execution latency | empty |
| capture function raises | `failed` | timestamp at the exception | latency until it failed | `"{ExcType}: {msg}"` (then re-raised) |

### CSV schema (column order)

| column | source |
|--------|--------|
| `scheduled_at` | `evt.scheduled_at` (UTC ISO-8601) |
| `fired_at` | `evt.fired_at` (UTC ISO-8601) |
| `drift_ms` | `(fired_at - scheduled_at).total_seconds() * 1000` |
| `outcome` | `fired` / `dropped` / `failed` |
| `camera` | `evt.camera_name` |
| `command` | `evt.command` |
| `description` | `evt.description` |
| `detail` | `evt.detail` (empty unless failed) |

---

## 3. Implementation

Ordered, independently-runnable phases — reverting the GUI phase must not break headless
capture.

### Phase 1: ShotEventBus

**Goal:** thread-safe, Qt-free pub/sub for shot outcomes.

Steps:
1. Create `src/solareclipseworkbench/shot_events.py` with `ShotOutcome`, `ShotEvent`,
   `ShotEventBus`, and module-level `BUS`.
2. `publish` iterates subscribers under a lock but invokes each outside the lock, wrapped
   in try/except that logs and continues.
3. Document the subscriber contract in `subscribe`'s docstring: callbacks run on the
   publishing (camera) thread and must return almost immediately — no I/O or blocking; hand
   heavy work off to another thread (see "Subscriber contract" in Design).
4. Add `tests/test_shot_events.py`: subscriber-order, isolation-on-raise, concurrent
   subscribe/publish.

### Phase 2: Instrument camera.py

**Goal:** publish `fired` / `dropped` / `failed` from `_serialised_on_camera`.

Steps:
1. Capture `scheduled_at = datetime.now(timezone.utc)` at wrapper entry.
2. Publish `DROPPED` in the lock-miss branch (unchanged warning + `return`).
3. Wrap `func(...)` in try/except/finally: publish `FIRED` on success, `FAILED` + re-raise
   on exception, release lock in `finally`.
4. Add `_describe_args(...)` private helper mirroring `JobsTableModel`'s settings
   formatting.
5. Confirm `python -c "import solareclipseworkbench.camera"` works without PyQt.

### Phase 3: GUI — status bar + row highlight

**Goal:** live counter and red rows on the GUI thread.

Steps:
1. Add `_ShotEventBridge(QObject)` with `event = pyqtSignal(object)`, subscribing `emit`
   to `BUS`; instantiate once and hold it on `SolarEclipseView`.
2. Add a permanent `QLabel` ("Missed: 0") to `self.statusBar()`; maintain
   `self._missed_counts: dict[str, int]`. Show `Missed: <total> (cam: n, ...)` and a red
   background once total > 0.
3. In `JobsTableModel`: add `self._missed_rows: set[int]`, a `mark_missed(camera_name,
   command, scheduled_at)` that matches the row by camera + command + `EXEC_TIME_UTC`
   within ±2 s and emits `dataChanged`, and extend `data()` to return red `BackgroundRole`
   / white `ForegroundRole` for missed rows.
4. The bridge slot must look up the **current** model via the controller each time (the
   model is recreated on schedule rebuild), not capture a startup reference.
5. Add `tests/test_jobs_table_model_missed.py`: `BackgroundRole` flip, ±2 s tolerance,
   multi-camera disambiguation.

### Phase 4: CSV post-run report

**Goal:** `*.shots.csv` next to the run log at shutdown.

Steps:
1. Add `ShotLog` (own module or on the view) — lock-guarded event list + `write_csv(path)`
   using stdlib `csv` and the schema above.
2. The bridge slot appends every event to `ShotLog`.
3. Derive the CSV path from the run-log stem set in [gui.py:2727](../../src/solareclipseworkbench/gui.py#L2727)
   (`{time_string}.log` → `{time_string}.shots.csv`). **Note:** this stem lives in
   `gui.py`'s `main()`, not `camera.py` as the source brief stated — see Open Questions.
4. Write from `SolarEclipseView.closeEvent` ([gui.py:882](../../src/solareclipseworkbench/gui.py#L882)),
   plus an `atexit` handler so non-GUI runs still produce a CSV.

### Phase 5: Integration test

**Goal:** end-to-end drop → counter → highlight → CSV.

Steps:
1. Add a slow virtual camera (`capture()` sleeps > `_MAX_LOCK_WAIT_S`).
2. Schedule three captures ~1 s apart; assert counter shows `Missed: 2`, two rows carry
   red `BackgroundRole`, and the CSV has the expected `dropped` rows with `drift_ms ≈ 1500`.

### Phase 6: Outcome

1. Review what was built against this spec.
2. Fill in the **Outcome** section — note deviations (esp. the log-path location).

### Phase 7: Documentation

Invoke `/docs` with a summary of the added modules (`shot_events`, `ShotLog`), the camera
instrumentation, and the GUI counter/CSV, plus a short README section on the missed-shot
indicator and the CSV report.

### Files

| File | Action | Description |
|------|--------|-------------|
| `src/solareclipseworkbench/shot_events.py` | Create | Bus, event, outcome enum. |
| `src/solareclipseworkbench/camera.py` | Modify | Publish from `_serialised_on_camera`; add `_describe_args`. |
| `src/solareclipseworkbench/gui.py` | Modify | Bridge, status bar, `JobsTableModel` highlight, CSV write hook. |
| `src/solareclipseworkbench/shot_log.py` | Create (or inline in gui) | `ShotLog` + `write_csv`. |
| `tests/test_shot_events.py` | Create | Bus unit tests. |
| `tests/test_jobs_table_model_missed.py` | Create | Row-highlight unit tests. |
| `tests/test_missed_shots_integration.py` | Create | Slow-camera end-to-end test. |

### Edge cases

| Case | Expected behavior |
|------|-------------------|
| Subscriber raises in `publish` | Caught + logged; other subscribers still run; camera thread unaffected. |
| Schedule rebuilt mid-run | Bridge resolves the current model each event; highlights keep working. |
| Two cameras, same scheduled time | `mark_missed` matches on camera + command, marking only the right row. |
| App closes before any shot | CSV written with header only (or skipped — see Open Questions). |
| `func` raises | `FAILED` event published, exception re-raised so existing error paths are unchanged. |

---

## 4. Verification

1. [ ] Sim run dropping shots shows `Missed: N` climbing live, red background once N > 0.
2. [ ] Each dropped shot's row turns red on the GUI thread within ~250 ms.
3. [ ] Closing the app writes `*.shots.csv` next to the log with one row per shot and
   populated `drift_ms`.
4. [ ] `_MAX_LOCK_WAIT_S` and silent-skip semantics unchanged; existing tests pass.
5. [ ] No new dependencies (stdlib `csv`/`dataclasses`/`threading`/`enum` + existing PyQt).
6. [ ] `python -c "import solareclipseworkbench.camera"` works without PyQt installed.

---

## 5. Open Questions

- **Log-path location.** The brief said `camera.py:main` builds the log filename (~line
  898). It is actually in `gui.py` `main()` ([gui.py:2727](../../src/solareclipseworkbench/gui.py#L2727))
  as `{time_string}.log`, and there is a second module-level config writing
  `/tmp/solareclipseworkbench.log` ([gui.py:71](../../src/solareclipseworkbench/gui.py#L71)).
  Decision needed: expose the run stem (e.g. a small module-level holder set in `main()`)
  vs. derive the CSV path some other way. Affects Phase 4 step 3.
- **Headless entry point.** Is there a true non-GUI capture entry (`__main__.py` / `sew.py`)
  that runs the scheduler without `SolarEclipseView`? If not, the `atexit` hook may be the
  only non-GUI path and the `closeEvent` write is the primary one.
- **Package-level Qt import (blocks Acceptance #6).** `solareclipseworkbench/__init__.py`
  does `from solareclipseworkbench.gui import sync_cameras`, so importing *any* submodule
  (`import solareclipseworkbench.camera`) runs `__init__.py` and pulls in PyQt — Acceptance
  criterion #6 (`camera.py` importable without PyQt) cannot hold at the package level until
  `__init__.py` is restructured (e.g. lazy/deferred GUI import). `shot_events.py` itself is
  Qt-free (verified in Phase 1); the leak is pre-existing in `__init__.py`, not introduced
  by this feature. Decide whether fixing it is in scope here or a separate cleanup.
- **Empty-run CSV.** Write a header-only CSV when no shots fired, or skip the file? (Lean:
  write header-only for predictability.)
- **Component doc root.** This spec lives in `docs/devel/` (repo already has a top-level
  `docs/`). Confirm this is the intended `<component>/docs/devel/` location before Wire-Up
  creates `INDEX.md` there.

---

## Outcome

<!-- Filled in during/after implementation. -->
