---
status: in-progress
issue: 4
pr: null
completed: []
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
 set Single defensively      set Continuous (Canon) then         set_single_config
 (not in shared adapter)     restore Single in finally           per shutter step
```

### Drive-mode ownership (Phase 1)

Move `drivemode=Single` **out** of the shared `__adapt_camera_settings`. Single-frame mode becomes:

- A Canon session-init constant (Phase 4), so the camera defaults to Single, **and**
- A defensive set at the start of `take_picture` only.

`take_burst` (Canon) explicitly requests a continuous drive mode *after* `__adapt_camera_settings` returns, then restores Single in a `finally` block so the next `take_picture` is deterministic. A new helper `_find_drive_mode_choice(widget, want_continuous)` — modelled on the existing `_find_capturemode_choice` ([camera.py:528](../../src/solareclipseworkbench/camera.py#L528)) — resolves the body-specific choice string: prefer a continuous choice containing `"high"`, else the only/first continuous choice.

Confirmed against a real 70D, the `drivemode` widget exposes: `Single`, `Continuous high speed`, `Continuous low speed`, `Single silent`, `Continuous silent`, `Timer 10 sec`, `Timer 2 sec`. So `want_continuous=True` resolves to `"Continuous high speed"` (the "contains high" rule selects it over the other two continuous options) and the restore resolves to `"Single"` (index 0, ahead of `"Single silent"`). This matches the literal already hardcoded at [camera.py:1735](../../src/solareclipseworkbench/camera.py#L1735).

This phase also reconciles the existing `get_camera_by_port` post-init `drivemode="Continuous high speed"` line ([camera.py:1735](../../src/solareclipseworkbench/camera.py#L1735)): with explicit per-command ownership, init should leave the camera in Single (deferred to Phase 4's session-init), not Continuous.

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

### Phase 1: Stop forcing Single drive mode in the shared adapter

**Goal:** `take_burst` produces a real Canon burst; `take_picture` stays deterministically single-frame.

Steps:
1. Remove the `drivemode=Single` mutation from `__adapt_camera_settings` ([camera.py:1019-1024](../../src/solareclipseworkbench/camera.py#L1019-L1024)).
2. Add a defensive `drivemode=Single` set at the start of the Canon path in `take_picture`.
3. Add `_find_drive_mode_choice(widget, want_continuous)` helper.
4. In `take_burst` Canon branch: set continuous drive after `__adapt_camera_settings`, wrap the Press/Release Full block in `try/finally`, restore Single in `finally`.
5. Reconcile `get_camera_by_port` post-init drivemode line ([camera.py:1735](../../src/solareclipseworkbench/camera.py#L1735)) — leave the body in Single at init.

### Phase 2: Per-camera settings cache + `set_single_config`

**Goal:** per-shot cost from ~600–1500 ms to ~100–300 ms when only shutter varies.

Steps:
1. Add module-level `_last_applied` dict and `_set_single` helper.
2. Rework `__adapt_camera_settings` with changed-only single-widget pushes (+ optional full-skip fast path); preserve aperture isolation and `_aperture_verified`.
3. Gate `capturetarget` re-assertion on Sony only.
4. **Cache coherence:** audit every command that drives a cached widget outside the adapter and reconcile `_last_applied` before returning — at minimum invalidate `_last_applied[name]` at the end of `take_hdr`; verify `take_burst`/`take_bracket`/`mirror_lock` don't touch cached keys.
5. Invalidate `_last_applied` in adapter `connect`/`disconnect`.
6. Log a debug line on cache miss.

### Phase 3: `take_hdr` uses `set_single_config` *(low priority — measurement-gated)*

**Goal:** modest speedup of the host-driven HDR ramp.

> **Note:** with native AEB rejected, this is the only HDR optimization on the table — but it's small. It saves one full config push per shot (~150 ms), while the dominant per-shot HDR cost is the camera-bound capture wait (`_wait_for_capture_complete`), which Phase 5 addresses. Implement this **only if** the measurement pass shows the per-shot config push (not the capture wait) is a meaningful share of HDR time. Otherwise skip it.

Steps:
1. Replace the full `gp_camera_set_config` in the HDR loop with `gp_camera_set_single_config(target, "shutterspeed", speed_widget, context)`.

### Phase 4: One-time Canon session init

**Goal:** move per-session constants out of the per-shot path.

Steps:
1. Add `ensure_session_initialised()` to `CanonCamera` with a `_session_initialised` flag (reset on connect/disconnect).
2. Push `autoexposuremodedial=Manual`, `drivemode=Single`, `capturetarget`=card in one `set_config`.
3. Call it at the top of `__adapt_camera_settings` for Canon; strip those constants from the per-shot path.

### Phase 5: Tighten `_wait_for_capture_complete` poll (optional)

**Goal:** a stuck event no longer stalls 3 s on Canon.

Steps:
1. Use `timeout_ms=500, max_events=10` on the Canon wait path; leave Sony untouched.

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

## 4. Verification

Criteria 1–3 require a physical Canon EOS 70D and are **hardware-gated**: they stay unchecked (pending a real-hardware run) while implementation proceeds against code review, the VirtualCamera simulator, and the existing test suite. Criteria 4–6 are validated without hardware.

1. [ ] _(hardware)_ `take_burst(duration=2.0)` on a 70D yields ≥10 frames (target ~14), confirmed by SD-card count.
2. [ ] _(hardware)_ 18-shot corona at 2 s spacing runs with zero `dropped` events in the missed-shots CSV.
3. [ ] _(hardware)_ 15-shot HDR completes in <10 s on a 70D.
4. [ ] No regression on Nikon/Sony across all capture commands.
5. [ ] Disconnect → reconnect → first shot applies all settings (cache-miss debug line present).
6. [ ] Headless run works; existing tests pass; no new dependencies.

---

## 5. Open Questions

- **Fast-path return contract:** exactly what `(context, config)` should the cache fast path return so every caller still works without a `get_config`? (Blocks Phase 2.)
- **Hardware validation:** acceptance criteria 1–3 require a physical 70D. Which runs can we validate in CI / on the simulator vs. only on real hardware?
- **Init drive mode vs. Phase 4:** should `get_camera_by_port` stop touching drive mode entirely and defer wholly to `ensure_session_initialised`, or keep a minimal init set?
- **Per-frame shot events:** the missed-shots feature treats each burst/HDR call as one event. Splitting per sub-shot would make burst verification easier but is independent of these perf fixes — defer?

---

## Outcome

<!-- Filled in during/after implementation. -->
