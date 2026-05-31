---
status: in-progress
issue: 4
pr: 5
completed:
  - "Phase 1: Fix the Canon burst (continuous drive in take_burst)"
  - "Phase 5: Fix _wait_for_capture_complete (break on FILE_ADDED)"
  - "Phase 4: Init drive-mode cleanup (reduced scope)"
---

# Canon Capture Performance — Design Document

> **Created:** May 2026

A Canon EOS 70D runs dramatically slower in SolarEclipseWorkbench (SEW) than in CaptureEclipse, and `take_burst` produces a single frame instead of a burst. The root cause is the per-shot USB overhead of the libgphoto2 backend combined with a drive-mode bug in the shared settings adapter. This document plans a set of independently-shippable fixes to the gphoto2 capture path in [camera.py](../../src/solareclipseworkbench/camera.py) without adding new dependencies. It is based on the `SEW_PERF_canon_slow.md` audit; line numbers in the audit predate the current working tree, so this spec re-anchors every reference against the live file.

> **Scope.** This spec covers the **burst correctness fix and modest per-shot perf hygiene** on the *existing* capture path.
>
> **Rejected alternative — native AEB offload.** We evaluated replacing the host-driven HDR/bracket ramp with the camera's native AEB (one continuous-drive burst per bracket). It does **not** fit SEW's model: `take_hdr` produces a *one-sided* exposure ramp anchored at the inner-corona (shortest) exposure ([camera.py:1481-1494](../../src/solareclipseworkbench/camera.py#L1481-L1494)), whereas Canon AEB is *symmetric* around a base; the per-camera base exposure varies with lens/filter (computed by `exposure_calculator.get_adjusted_exposure`); and the 70D's AEB is limited to **3 frames** in 1/3-EV spreads (frame count not even discoverable over libgphoto2 — it's buried in the `customfuncex` blob). Mapping the asymmetric ramp onto symmetric 3-frame groups would need a capability model + tiling planner for little real gain, and Canon EDSDK offers no bracketing capability libgphoto2 lacks. **Dropped.**
>
> The perf phases below are **gated on a measurement pass** against a real 70D (per-stage `perf_counter` timing), because the audit's priority order is an estimate: drops may be caused by the `_wait_for_capture_complete` poll stall, not the config pushes. Measure first, then build the phases the data justifies.

---

## 1. Motivation

### Current state

All capture commands (`take_picture`, `take_burst`, `take_hdr`, `take_bracket`) funnel through `__adapt_camera_settings` ([camera.py:988](../../src/solareclipseworkbench/camera.py#L988)), which on **every shot**:

1. `gp_camera_get_config` — pulls the full config tree (~100–300 ms on Canon).
2. Mutates `autoexposuremodedial=Manual`, `drivemode=Single`, `iso`, `shutterspeed`, `capturetarget` in memory.
3. `_set_gp_config` — pushes the **whole tree** (~150–300 ms).
4. Mutates `aperture`.
5. `_set_gp_config` — pushes the **whole tree again** (~150–300 ms).
6. First-shot-only aperture read-back verify (already cached via `_aperture_verified`).

`take_picture` then adds `trigger_capture` + `_wait_for_capture_complete` + `_drain_camera_events`. **Per-shot floor on a 70D: ~600–1500 ms**, even when nothing but the shutter speed changed between consecutive shots.

Two concrete defects compound this:

- **Burst is broken on Canon.** `__adapt_camera_settings` unconditionally forces `drivemode=Single` ([camera.py:1019-1024](../../src/solareclipseworkbench/camera.py#L1019-L1024)). `take_burst` calls the adapter first, then holds the shutter via `eosremoterelease` Press Full → sleep → Release Full ([camera.py:1186-1198](../../src/solareclipseworkbench/camera.py#L1186-L1198)). Holding the shutter in Single drive yields exactly **one frame**, regardless of `duration`.
- **`take_hdr` re-pushes the full tree per iteration** ([camera.py:1506-1519](../../src/solareclipseworkbench/camera.py#L1506-L1519)) even though only `shutterspeed` changes between shots.

Note: `get_camera_by_port` already runs a post-init block that sets `capturetarget` to the memory card and `drivemode` to `"Continuous high speed"` ([camera.py:1723-1741](../../src/solareclipseworkbench/camera.py#L1723-L1741)). This is the natural home for one-time Canon session constants — and its current `drivemode` choice will need reconciling with the per-command drive-mode logic.

### Goal

- `take_burst(duration=2.0)` on a 70D produces a real burst (~14 frames at 7 fps continuous-high; accept ≥10).
- A constant-ISO/aperture corona ladder (only shutter varies) drops per-shot cost from ~600–1500 ms to ~100–300 ms — no `dropped` events at 2 s spacing.
- A 15-shot HDR completes in <10 s on a 70D (≈25 s today).
- No regression on Nikon/Sony; new logic is Canon-gated or applies cleanly to all vendors.
- Headless runs still work; no new Qt/threading dependencies.

### Use cases

- Pre-C2 / C2 / C3 Baily's beads and diamond-ring bursts that currently capture one frame.
- The 18-shot corona pattern fired at ~2 s spacing during totality.
- HDR sequences in the partial phases.

### Operational model (why this shapes the design)

SEW does **not** fire one homogeneous burst. A schedule is a long list of *independent* commands, each fired by its own APScheduler thread at a precise eclipse-relative time, and **each command reconfigures the camera** through `__adapt_camera_settings`:

- **Consecutive scheduled shots usually differ** — a corona ladder steps shutter speed shot-to-shot; the schedule interleaves `take_picture`, `take_hdr`, `take_bracket`, `take_burst` with different ISO/shutter/aperture. So a "nothing changed" state is the *exception*, not the rule.
- **`take_hdr` is an exposure ramp, not a burst** — it issues `2*stops+1` shots at *different* shutter speeds (ISO/aperture fixed), driving the `shutterspeed` widget directly inside its own loop, *outside* `__adapt_camera_settings`.
- **`take_burst` is a held shutter / continuous-drive sequence** of same-setting frames — a genuinely different mechanism from HDR.
- **Timing is the hard constraint.** A job that can't grab the USB lock within `_MAX_LOCK_WAIT_S` (1.5 s, [camera.py:556](../../src/solareclipseworkbench/camera.py#L556)) is *dropped* to protect the timing of later shots. Every millisecond shaved off per-shot reconfiguration directly reduces drops — that, not raw throughput, is the real goal.

Two consequences for Phase 2 (settings cache):

1. The full-skip fast path will rarely fire across independent scheduled commands; the dominant win is **fewer widgets pushed per shot**, not zero-traffic skips.
2. The cache is only trustworthy if every command that mutates a cached widget (`iso`/`shutterspeed`/`aperture`) keeps `_last_applied` in sync — see "Cache coherence" in §2.

### Concepts

| Term | Definition |
|------|------------|
| Full config push | `gp_camera_set_config` of the entire widget tree — one expensive USB round-trip (~150–300 ms on Canon). |
| Single-widget push | `gp_camera_set_single_config(target, name, widget, ctx)` — pushes only one property (~30–80 ms on Canon). |
| Settings cache | Per-camera record of the last-applied iso/shutter/aperture, used to skip USB traffic when nothing changed. |
| Session init | One-time push of Canon constants (`autoexposuremodedial`, drive mode, `capturetarget`) that never change mid-session. |

---

## 2. Design

The capture path stays gphoto2-only. We attack the four cost centres in order of impact. Each is a self-contained change to [camera.py](../../src/solareclipseworkbench/camera.py).

```
                       ┌─────────────────────────────────────────────┐
  every capture call → │ __adapt_camera_settings                      │
                       │  ─ today: get_config + 2× full push, always  │
                       │  ─ after: cache check → 0–N single pushes    │
                       └───────────────┬──────────────────────────────┘
                                       │ (context, config)
      ┌────────────────────────────────┼────────────────────────────────┐
      ▼                                ▼                                 ▼
 take_picture                     take_burst                         take_hdr
 stays Single                set Continuous (Canon) then         (host ramp;
 (adapter asserts it)        restore Single in finally           wait fix in P5)
```

### Drive-mode ownership (Phases 1 & 4)

Drive mode is owned per-command, not by the shared adapter:

- **`take_burst`** (Phase 1) explicitly sets the body's fastest continuous mode *after* `__adapt_camera_settings` returns, then restores Single in a `finally` block (so a mid-burst error still leaves the camera deterministic).
- **Single-frame** for every other command stays cheap: it remains `__adapt_camera_settings`'s batched in-memory mutation — **zero extra round-trip**, since it rides the adapter's existing config push. (Phase 4 originally planned to move this to a one-time session-init constant, but the measurement showed config writes are ~1.4% of a shot, so that refactor was dropped — see Phase 4. The per-shot assertion stays for robustness.)
- **Init** (`get_camera`/`get_camera_by_port`) establishes the documented default of `Single` at connect (Phase 4), replacing a misleading `"Continuous high speed"` write that was immediately overridden.

A new helper `_find_drive_mode_choice(widget, want_continuous)` — modelled on the existing `_find_capturemode_choice` ([camera.py:528](../../src/solareclipseworkbench/camera.py#L528)) — resolves the body-specific choice string: for continuous, prefer a choice containing `"high"`, else the first `"continuous"`; for single, the first `"single"`.

Confirmed against a real 70D, the `drivemode` widget exposes: `Single`, `Continuous high speed`, `Continuous low speed`, `Single silent`, `Continuous silent`, `Timer 10 sec`, `Timer 2 sec`. So `want_continuous=True` resolves to `"Continuous high speed"` (the "contains high" rule selects it over the other two continuous options) and the restore resolves to `"Single"` (index 0, ahead of `"Single silent"`).

> **Why Single stays in the adapter for Phase 1.** Removing it from `__adapt_camera_settings` and adding a *separate* `drivemode=Single` push to `take_picture` (the audit's original split) would add a full config round-trip to **every** single shot — exactly the overhead Phase 2 sets out to remove. The burst bug is fully fixed by `take_burst` overriding to continuous; the adapter's Single is harmless for burst (overridden) and free for everyone else. So the adapter cleanup + `get_camera_by_port` init reconcile (its current `drivemode="Continuous high speed"` at [camera.py:1735](../../src/solareclipseworkbench/camera.py#L1735) → Single) move to **Phase 4**, where eliminating per-shot drive-mode writes is the actual objective.

### Settings cache + single-widget push (Phase 2)

A module-level `_last_applied: dict[str, dict]` keyed by `camera_settings.camera_name`. `__adapt_camera_settings`:

- Builds the desired `{iso, shutterspeed, aperture}` dict.
- `get_config` once, then push **only changed** widgets via `gp_camera_set_single_config` (helper `_set_single`), keeping aperture in its own isolated push and preserving the `_aperture_verified` short-circuit.
- Gate the `capturetarget` re-assertion on **Sony only** (the existing comment confirms only Sony resets it between shots) — saves another ~100 ms per Canon shot.
- **Full-skip fast path** (desired == cached) is a *bonus*, not the main win: per the operational model, consecutive scheduled shots usually differ, so this rarely fires. The throughput comes from pushing 1 changed widget instead of the whole tree twice. Keep the fast path, but don't size the design around it.

Realistic per-shot effect for a corona ladder (only shutter changes): one `get_config` + one single-widget `shutterspeed` push, vs. today's `get_config` + two full-tree pushes + a Canon `capturetarget` push.

#### Cache coherence (correctness, not perf)

The cache records *intent*, but several commands drive cached widgets **directly, outside `__adapt_camera_settings`** — chiefly `take_hdr`, which ramps `shutterspeed` shot-by-shot in its own loop. After such a command, `_last_applied[name]['shutterspeed']` no longer matches the camera's physical state. If the next scheduled `take_picture` requests that stale value, the changed-only logic would **skip the push while the camera sits on the wrong speed → a silent wrong-exposure frame.**

Rule: **any command that mutates a cached widget outside the adapter must reconcile the cache before returning** — either update `_last_applied[name]` to the camera's final state, or invalidate the affected key(s) so the next adapter call re-pushes them. Phase 2 must audit `take_hdr` (drives `shutterspeed`), `take_burst`/`take_bracket` (`eosremoterelease`/`aeb` — *not* cached keys, but verify), and `mirror_lock`. Simplest safe default: invalidate the whole `_last_applied[name]` entry at the end of `take_hdr`.

Cache must also be invalidated on connect/disconnect (`_last_applied.pop(cam_key, None)`), keyed by name so reconnects behave. A debug log line on cache miss makes invalidation testable.

> Open design point: the current signature returns `(context, config)` and callers reuse `config`. The fast path needs to still hand callers a usable context (and possibly config). Phase 2 must define exactly what the fast path returns without breaking `take_picture`/`take_burst`/`take_hdr`/`take_bracket`, all of which consume `config`.

### `take_hdr` single-widget push (Phase 3)

Replace `gp_camera_set_config(target, config, context)` in the loop ([camera.py:1510](../../src/solareclipseworkbench/camera.py#L1510)) with `gp_camera_set_single_config(target, "shutterspeed", speed_widget, context)`. Only the shutter widget changes per iteration; everything else was already applied once.

### One-time Canon session init (Phase 4)

A Canon-only `ensure_session_initialised()` that pushes the constants `autoexposuremodedial=Manual`, drive mode = Single, `capturetarget` = card in a single `set_config`, guarded by a `_session_initialised` flag (reset on connect/disconnect). Called at the top of `__adapt_camera_settings` for Canon. Then strip `autoexposuremodedial` and `drivemode` out of the per-shot path. Idempotent and cheap after the first call.

### `_wait_for_capture_complete` poll tightening (Phase 5, optional)

`_wait_for_capture_complete` ([camera.py:654](../../src/solareclipseworkbench/camera.py#L654)) uses `timeout_ms=3000, max_events=30`. A healthy 70D signals CAPTURE_COMPLETE in 100–300 ms, so a single stuck event blocks 3 s. Drop to `timeout_ms=500, max_events=10` on the Canon path (leave Sony's distinct drain path untouched).

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend | Stay on libgphoto2 | EDSDK is Windows-only, NDA-gated, multi-week, breaks cross-platform single stack. Out of scope. |
| Per-property updates | `set_single_config` | ~30–80 ms vs ~150–300 ms full-tree push; libgphoto2 supports it. |
| Cache key | `camera_settings.camera_name` | Survives camera-object churn across reconnects. |
| Drive-mode owner | per-command + session-init | Removes the shared-adapter coupling that broke burst. |

---

## 3. Implementation

Phases mirror the audit's suggested PR layout. Each is independently testable; **Phase 1 is the user-visible bug and ships first.**

> **Measurement gate.** Phase 1 (burst correctness) ships unconditionally. Phases 2–5 are **gated on a measurement pass**: instrument the Canon capture path with `perf_counter` around `get_config`, each config push, and `_wait_for_capture_complete`, then run one representative corona sequence on the 70D. Only build the perf phases the data justifies — if drops trace to the capture-wait stall, Phase 5 matters more than Phases 2–4; if they trace to config pushes, Phase 2 leads. Do not implement 2–5 blind on the audit's estimates.
>
> **RESULT (2026-05-31, real 70D — see Outcome for the table).** The wait dominates overwhelmingly: per `take_picture` ≈ **5.7 s wall, of which ~5.46 s (96%) is `_wait_for_capture_complete`**; `get_config` ≈ 24 ms and both config pushes ≈ 57 ms combined. So the audit's premise — ~600–1500 ms of per-shot *config* overhead — is **false on this body** (config is ~80 ms, ~1.4%). **Phase 5 is now the lead and the only phase that matters; Phase 2 is deprioritized (~1% saving) and Phase 3 is dropped (HDR per-shot is 5.41 s wait vs 36 ms push).** The 5.7 s/shot floor also explains drops directly: it exceeds `_MAX_LOCK_WAIT_S` (1.5 s), so any shot scheduled within ~6 s of another is dropped. Next step is an event-trace to learn *why* the wait is 5.4 s before designing the Phase 5 fix.

### Phase 1: Fix the Canon burst (continuous drive in `take_burst`)

**Goal:** `take_burst` produces a real Canon burst; `take_picture` stays deterministically single-frame.

Steps:
1. Add the `_find_drive_mode_choice(widget, want_continuous)` helper, modelled on `_find_capturemode_choice`.
2. In the `take_burst` Canon branch: after `__adapt_camera_settings`, set the body's fastest continuous drive via the helper and push; wrap the Press/Release Full block in `try`; restore Single in a `finally` (so a mid-burst error still leaves the camera deterministic).

**Deviation from the audit's split (see Drive-mode ownership above):** removing `drivemode=Single` from `__adapt_camera_settings` and adding a defensive Single push to `take_picture` is *not* done here — it would add a per-shot round-trip. `__adapt` keeping its batched Single is harmless (burst overrides it) and free for non-burst commands, so the adapter cleanup + `get_camera_by_port` init reconcile move to **Phase 4**.

### Phase 2: Per-camera settings cache + `set_single_config` *(deprioritised — measurement says ~1% win)*

**Goal (revised by measurement):** the original premise (~600–1500 ms/shot in config) was false on the 70D — config pulls+pushes are ~80 ms/shot (~1.4% of the ~5.7 s wall). This phase saves almost nothing on its own and only matters as scaffolding if a future body proves config-bound. **Do not build before Phase 5; likely skip.**

Steps:
1. Add module-level `_last_applied` dict and `_set_single` helper.
2. Rework `__adapt_camera_settings` with changed-only single-widget pushes (+ optional full-skip fast path); preserve aperture isolation and `_aperture_verified`.
3. Gate `capturetarget` re-assertion on Sony only.
4. **Cache coherence:** audit every command that drives a cached widget outside the adapter and reconcile `_last_applied` before returning — at minimum invalidate `_last_applied[name]` at the end of `take_hdr`; verify `take_burst`/`take_bracket`/`mirror_lock` don't touch cached keys.
5. Invalidate `_last_applied` in adapter `connect`/`disconnect`.
6. Log a debug line on cache miss.

### Phase 3: `take_hdr` uses `set_single_config` *(DROPPED — measurement)*

**Goal:** modest speedup of the host-driven HDR ramp.

> **Dropped.** The measurement settles it: HDR per-shot is ~5.41 s wait vs ~36 ms config push. Replacing the push with `set_single_config` saves <1% of HDR time. Not worth doing. The HDR win, if any, comes entirely from Phase 5.

Steps:
1. Replace the full `gp_camera_set_config` in the HDR loop with `gp_camera_set_single_config(target, "shutterspeed", speed_widget, context)`.

### Phase 4: Init drive-mode cleanup *(reduced scope — measurement)*

**Original goal** was to move per-session constants out of the per-shot path via a `CanonCamera.ensure_session_initialised()` hook and strip `autoexposuremodedial`/`drivemode` from `__adapt_camera_settings`.

**Reduced post-measurement.** Config writes are ~1.4% of a shot and those mutations are *batched* into the existing push, so the refactor saves **0 ms** while churning the now-validated hot path and removing the per-shot re-assertion of a known state (a small robustness loss). Not worth it for a reliability-critical tool. **The session-init refactor and the strip-from-`__adapt` are dropped.**

What *was* done — the genuinely useful, zero-risk part:
1. Both init paths (`get_camera` and `get_camera_by_port`) set `drivemode="Continuous high speed"` for **all** cameras at connect, which was immediately overridden (Canon) or left stale (non-Canon) — misleading dead writes. Replaced with the documented default via `_find_drive_mode_choice(want_continuous=False)` → `Single`, guarded (skips when the widget/choice is absent). Per-command code owns drive mode from there: `take_picture` stays Single, `take_burst` opts into continuous and restores Single.
2. `__adapt_camera_settings` is left as-is — its batched `drivemode=Single` / `autoexposuremodedial=Manual` are free and keep every non-burst shot deterministic.

### Phase 5: Fix `_wait_for_capture_complete` — **THE lead phase**

**Goal:** cut the ~5.4 s/shot capture wait that is ~96% of per-shot time and the direct cause of dropped shots (it exceeds the 1.5 s lock guard). This is the whole performance story on the 70D.

**Root cause (event-trace, 2026-05-31 — see Outcome).** The 70D **never emits `CAPTURE_COMPLETE`**. After a trigger it streams `UNKNOWN` property-change events, emits one **`FILE_ADDED` at ~1.2 s** (image committed to card = shot done), goes quiet ~2.3 s, and the loop — which only breaks on `CAPTURE_COMPLETE`/`TIMEOUT` — then blocks until the **first `TIMEOUT` at ~5.3 s**. That 5.3 s is the entire per-shot cost.

**Fix (implemented):** add `GP_EVENT_FILE_ADDED` to the break condition in `_wait_for_capture_complete`. The loop now returns when the image lands on the card (~1.2 s) instead of waiting for a `CAPTURE_COMPLETE` that never comes. `timeout_ms` stays 3000 (real events return immediately; it only bounds the idle fallback, and a shorter value risks `TIMEOUT`-breaking during the ~0.6 s gap before `FILE_ADDED`). Applies to all bodies — it's a strict improvement (break on the earliest of CAPTURE_COMPLETE / FILE_ADDED / TIMEOUT); Sony is unaffected (it returns before this function).

Steps:
1. Break on `GP_EVENT_FILE_ADDED` as well as `CAPTURE_COMPLETE`/`TIMEOUT`. *(done)*
2. Validate on the 70D with `perf_probe.py`: expect `take_picture` wall ≈1.2–1.5 s (was ~5.7 s), HDR ≈9 s (was 39 s), and **zero new `failed`/`-110` errors**.

### Phase 6: Outcome

1. Review what was built against this spec.
2. Fill in the **Outcome** section — note deviations and why.

### Phase 7: Documentation

Invoke `/docs` with a summary of the changed capture path (drive-mode ownership, settings cache, session init) so user-facing/dev docs stay in sync.

### Files

| File | Action | Description |
|------|--------|-------------|
| [src/solareclipseworkbench/camera.py](../../src/solareclipseworkbench/camera.py) | Modify | All capture-path changes (Phases 1–5). |
| `tests/` | Modify/Create | Burst-frame-count and cache-invalidation coverage where the existing harness allows. |

### Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Body has no `drivemode` widget | Continuous/Single sets are skipped silently; burst still fires (one frame), no crash. |
| No continuous choice found | `_find_drive_mode_choice` returns None; burst logs a warning and proceeds. |
| Disconnect → reconnect → first shot | Cache miss re-applies all settings; session re-initialises. |
| `take_hdr` then `take_picture` at HDR's start shutter | Cache reconciled after HDR, so the shutter push is **not** skipped — no silent wrong-exposure frame. |
| Aperture not settable (telescope/fixed lens) | Isolated aperture push still fails gracefully; iso/shutter unaffected. |
| Non-Canon vendors | Phase 1/4 logic Canon-gated; cache/HDR changes apply cleanly to all. |

---

## 4. Evaluation protocol

Every phase is validated by a **before/after measurement on the real 70D**, not by inspection. Most of this spec past Phase 1 rests on estimates (the audit's per-stage costs, the `set_single_config` speedup assumption), so the measurement *is* the evaluation — a phase that doesn't move its metric, or regresses another, does not land.

### Instruments (already available — little to build)

1. **Missed-shots CSV report** (from #1) — logs `fired`/`dropped`/`failed` per shot. The before/after source of truth for **drops**, the metric that actually matters during totality. Diff the CSV across runs.
2. **`perf_counter` instrumentation** — added once in the measurement pass: wrap `gp_camera_get_config`, each config push, and `_wait_for_capture_complete` ([camera.py:654](../../src/solareclipseworkbench/camera.py#L654)) on the Canon path; emit per-stage ms at debug level. This is the timing baseline reused by every perf phase.
3. **VirtualCamera simulator** — regression only: catches crashes, wrong frame counts, logic errors. It has **no USB cost**, so it proves nothing about timing. Never cite a simulator run as a perf result.

### Bench sequence

A single fixed schedule, run identically before and after each phase so comparisons are apples-to-apples:

- one 18-shot corona ladder at 2 s spacing (constant ISO/aperture, varying shutter),
- one `take_burst(2.0)`,
- one `take_hdr(stops=5)`.

Same camera, lens, card, and a charged battery each time. Commit it under `tests/bench/` (or document the script path) so it's reproducible.

### Discipline

- Run the bench **3–5 times** per measurement; compare **medians**, not single runs — USB/card/battery/thermal variance is real and a single run will mislead.
- Capture **both** artifacts every run (CSV + perf log).
- Record before/after medians in the **Outcome** section as each phase lands — that is the evidence trail, and the gate for proceeding to the next perf phase.

### Per-phase metric

| Phase | Primary metric | Pass condition |
|-------|----------------|----------------|
| 1 — Burst fix | frames from one `take_burst(2.0)` (SD-card count) | 1 → ≥10 (target ~14) |
| Measurement pass | per-stage ms (`get_config` / pushes / wait) | baseline captured; identifies dominant cost centre |
| 2 — Settings cache | per-shot reconfig ms + corona drops | pushes ↓ **and** drops not worse |
| 3 — HDR `set_single_config` | total HDR wall-clock | measurable drop, else skip the phase |
| 4 — Session init | per-shot ms | **flat — "no regression" is the pass**, no delta expected |
| 5 — Wait-poll tightening | capture-wait ms + drops | wait-stalls ↓ **and** no new `failed`/`-110` errors |

> **Hardware-access reality:** if the 70D is on hand, test after each phase. If access is intermittent, batch — ship Phase 1 + the instrumentation, then run one hardware session that baselines and validates Phases 2–5 together. Either way, no perf phase merges without its before/after numbers in the Outcome.

---

## 5. Verification

Criteria 1–3 require a physical Canon EOS 70D and are **hardware-gated**: they stay unchecked (pending a real-hardware run) while implementation proceeds against code review, the VirtualCamera simulator, and the existing test suite. Criteria 4–6 are validated without hardware.

1. [x] _(hardware)_ `take_burst(duration=2.0)` on a 70D yields ≥10 frames (target ~14), confirmed by SD-card count. **Validated 2026-05-31: 18 frames** (vs. 1 before the fix), shutter burst audible; counted via `FILE_ADDED` events with `tests/bench/burst_check.py`.
2. [~] _(hardware)_ 18-shot corona at 2 s spacing runs with zero `dropped` events. **Strongly implied, not yet scheduler-tested:** per-shot is now ~1.26 s (was ~5.7 s), under both the 1.5 s drop guard and the 2 s cadence. A full APScheduler 2 s-spacing run is the remaining confirmation.
3. [~] _(hardware)_ 15-shot HDR. **Target revised:** the original "<10 s" reflected the audit's wrong cost model. Measured per-shot floor is ~1.31 s (camera-bound RAW write), so a 15-shot HDR is **~20 s — down from ~84 s, a 4× win**, but not <10 s. <10 s is unreachable while we wait for `FILE_ADDED` (the safe completion signal).
4. [ ] No regression on Nikon/Sony across all capture commands. *(Phase 5 `FILE_ADDED` break is a strict improvement for all bodies; Sony unaffected — not yet re-tested on Nikon/Sony hardware.)*
5. [n/a] Disconnect → reconnect → first shot applies all settings (cache-miss debug line). *(Phase 2 settings cache deprioritised by the measurement — no cache built.)*
6. [x] Headless run works; existing tests pass (35 incl. 6 new); no new dependencies.

---

## 6. Open Questions

- **Fast-path return contract:** exactly what `(context, config)` should the cache fast path return so every caller still works without a `get_config`? (Blocks Phase 2.)
- **Hardware validation:** acceptance criteria 1–3 require a physical 70D. Which runs can we validate in CI / on the simulator vs. only on real hardware?
- **Init drive mode vs. Phase 4:** should `get_camera_by_port` stop touching drive mode entirely and defer wholly to `ensure_session_initialised`, or keep a minimal init set?
- **Per-frame shot events:** the missed-shots feature treats each burst/HDR call as one event. Splitting per sub-shot would make burst verification easier but is independent of these perf fixes — defer?

---

## Outcome

<!-- Filled in during/after implementation. -->

**Measurement pass (2026-05-31, real 70D, `tests/bench/perf_probe.py`).** Per-op timing of the Canon capture path, median across 6 `take_picture` shots (corona-ladder shutters, constant ISO/aperture) + one 7-shot `take_hdr`:

| Command | get_config | set_config (pushes) | wait_for_event | wall |
|---------|-----------|---------------------|----------------|------|
| `take_picture` (median/shot) | ~24 ms | ~57 ms (2 calls) | **~5460 ms (26 calls)** | ~5706 ms |
| `take_hdr` (per shot, /7) | ~5 ms | ~36 ms | **~5412 ms** | ~5592 ms |

**Verdict:** the capture wait is ~96% of per-shot time; config pushes are ~1.4%. This **inverts the audit's plan**. Re-prioritisation: **Phase 5 (wait) is the lead and effectively the whole win; Phase 2 (cache) deprioritised (~1% saving); Phase 3 (HDR push) dropped.** The ~5.7 s/shot floor is also the direct cause of dropped shots (it exceeds the 1.5 s `_MAX_LOCK_WAIT_S` guard).

**Event-trace (2026-05-31, `tests/bench/event_trace.py`) — root cause of the 5.4 s wait.** One `trigger_capture`, then every `wait_for_event` logged: 23 `UNKNOWN`, 1 `FILE_ADDED` (at **+1177 ms** — image on card), 3 `TIMEOUT`, and **zero `CAPTURE_COMPLETE`**. The 70D never sends `CAPTURE_COMPLETE`; the loop (break only on CAPTURE_COMPLETE/TIMEOUT) therefore blocks until the first `TIMEOUT` at **+5340 ms** — matching the ~5.46 s measured. **Phase 5 fix:** also break on `GP_EVENT_FILE_ADDED`, so the wait ends when the image lands on the card (~1.2 s) instead of at the 5.3 s timeout.

**Phase 4 (init drive-mode cleanup) — reduced & landed (2026-05-31).** The measurement removed the perf rationale (config writes ~1.4%), so the session-init refactor and the strip-from-`__adapt` were **dropped** (0 ms gain, churns validated code, less robust). Kept the zero-risk part: `get_camera` and `get_camera_by_port` now set the documented default `Single` (via `_find_drive_mode_choice`) instead of a misleading `"Continuous high speed"` that was immediately overridden. `__adapt_camera_settings` unchanged. Behavior-neutral — init drive mode is overridden by per-command code in every capture path — so no new hardware validation required; suite green.

**Phase 5 (wait fix) — landed & hardware-validated (2026-05-31).** Added `GP_EVENT_FILE_ADDED` to the `_wait_for_capture_complete` break condition. On the 70D, `take_picture` median wall **5706 ms → 1259 ms** (wait 5460 → 1087 ms) and a 7-shot `take_hdr` **39.1 s → 9.2 s** — ~4.5× — with no `-110`/failed errors and all frames captured. The residual ~1.1 s/shot is the camera-bound RAW-write time (`FILE_ADDED`), the real floor. This is the single highest-impact change in the spec and also resolves the dropped-shot cadence problem (per-shot now < the 1.5 s lock guard). **Phases 2 and 3 are intentionally not implemented** (measurement showed config pushes are ~1.4% of per-shot time); they remain documented as deprioritised/dropped. Bench tools `tests/bench/perf_probe.py` (per-op timing) and `tests/bench/event_trace.py` (event timeline) added.

**Phase 1 (burst fix) — landed & hardware-validated (2026-05-31).** Added `_find_drive_mode_choice` and reworked the `take_burst` Canon branch to switch to `Continuous high speed` for the burst and restore `Single` in a `finally`. *Deviation from the audit's split:* the `drivemode=Single` removal from `__adapt_camera_settings`, the `take_picture` defensive set, and the `get_camera_by_port` init reconcile were **not** done here — they'd add a per-shot round-trip — and moved to Phase 4 (session init). `__adapt` keeps its batched Single (free, deterministic for non-burst commands); `take_burst` overrides it. Result on a real 70D: a 2.0 s burst produced **18 frames** (was 1). Added `tests/test_camera_drive_mode.py` (6 hardware-free helper tests) and `tests/bench/burst_check.py` (manual FILE_ADDED-counting harness).
