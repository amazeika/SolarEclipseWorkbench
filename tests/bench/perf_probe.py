#!/usr/bin/env python3
"""Manual hardware bench: measure where per-shot time goes on Canon (#4).

The measurement pass that gates Phases 2-5 of the Canon performance spec.
Instead of editing production code, it monkeypatches the three expensive
libgphoto2 calls — ``gp_camera_get_config`` (full config pull),
``gp_camera_set_config`` (full config push), and ``gp_camera_wait_for_event``
(capture-complete / event polling) — to time every call, then runs a
representative sequence on the connected 70D and reports the breakdown.

The question it answers: is per-shot cost dominated by **config pushes**
(→ Phase 2 settings cache leads) or the **capture wait** (→ Phase 5 poll
tightening leads)?  Do not build Phases 2-5 before reading this output.

NOT a pytest test — drives hardware and fires the shutter (~13 frames total:
6 take_picture + a 7-shot take_hdr).  Run with the 70D connected:

    .venv/bin/python tests/bench/perf_probe.py

macOS: run `sudo pkill -9 PTPCamera` first if gphoto2 can't claim the camera.
"""

import logging
import statistics
import time

import gphoto2 as gp

from solareclipseworkbench.camera import (
    CameraSettings,
    get_cameras,
    get_camera_by_port,
    take_picture,
    take_hdr,
)

# (op_name, elapsed_ms) appended by the wrappers; cleared per command invocation.
_records = []
_OPS = ("gp_camera_get_config", "gp_camera_set_config", "gp_camera_wait_for_event")


def _install_timers():
    for name in _OPS:
        original = getattr(gp, name)

        def make(orig):
            def wrapper(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return orig(*args, **kwargs)
                finally:
                    _records.append((wrapper.__op__, (time.perf_counter() - t0) * 1000.0))
            return wrapper

        w = make(original)
        w.__op__ = name
        setattr(gp, name, w)


def _run(label, fn, table):
    """Run one capture command, capturing per-op timing for that invocation."""
    _records.clear()
    t0 = time.perf_counter()
    fn()
    wall = (time.perf_counter() - t0) * 1000.0
    row = {"cmd": label, "wall": wall}
    for op in _OPS:
        vals = [ms for (o, ms) in _records if o == op]
        row[op] = (len(vals), sum(vals))
    table.append(row)
    short = {"gp_camera_get_config": "get", "gp_camera_set_config": "set", "gp_camera_wait_for_event": "wait"}
    parts = " ".join(f"{short[o]}={row[o][1]:6.0f}ms/{row[o][0]}" for o in _OPS)
    print(f"  {label:<22} wall={wall:7.0f}ms   {parts}")


def _summary(rows, title):
    if not rows:
        return
    print(f"\n  --- {title} (median across {len(rows)} runs) ---")
    for op in _OPS:
        sums = [r[op][1] for r in rows]
        ns = [r[op][0] for r in rows]
        print(f"    {op:<28} median {statistics.median(sums):6.0f}ms  "
              f"(calls/run median {statistics.median(ns):.0f})")
    print(f"    {'wall':<28} median {statistics.median([r['wall'] for r in rows]):6.0f}ms")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)

    cams = get_cameras()
    if not cams:
        print("No camera detected. On macOS: sudo pkill -9 PTPCamera, then retry.")
        return 1
    name, port = next(((n, p) for n, p in cams if "Canon" in n), cams[0])
    print(f"Using camera: {name} @ {port}\n")
    camera = get_camera_by_port(name, port, alias=name)

    _install_timers()

    # --- take_picture corona ladder: vary shutter, constant ISO/aperture ---
    print("take_picture ladder:")
    pic_rows = []
    ladder = ["1/1000", "1/500", "1/250", "1/1000", "1/500", "1/250"]
    for sp in ladder:
        s = CameraSettings(camera_name=name, shutter_speed=sp, aperture="8", iso=400)
        _run(f"take_picture {sp}", lambda s=s: take_picture(camera, s), pic_rows)

    # --- take_hdr: one 7-shot ramp (stops=3) ---
    print("\ntake_hdr:")
    hdr_rows = []
    s = CameraSettings(camera_name=name, shutter_speed="1/1000", aperture="8", iso=400)
    _run("take_hdr stops=3", lambda: take_hdr(camera, s, 3), hdr_rows)

    _summary(pic_rows, "take_picture")
    hdr = hdr_rows[0]
    n_shots = 7
    print(f"\n  --- take_hdr (7 shots, per-shot = total/{n_shots}) ---")
    for op in _OPS:
        cnt, tot = hdr[op]
        print(f"    {op:<28} total {tot:6.0f}ms over {cnt} calls  (~{tot/n_shots:5.0f}ms/shot)")
    print(f"    {'wall':<28} total {hdr['wall']:6.0f}ms  (~{hdr['wall']/n_shots:5.0f}ms/shot)")

    # --- verdict hint ---
    if pic_rows:
        med_set = statistics.median([r["gp_camera_set_config"][1] for r in pic_rows])
        med_wait = statistics.median([r["gp_camera_wait_for_event"][1] for r in pic_rows])
        print("\n  VERDICT (take_picture): "
              + ("config pushes dominate → Phase 2 (settings cache) leads"
                 if med_set >= med_wait else
                 "capture wait dominates → Phase 5 (poll tightening) leads")
              + f"  [set={med_set:.0f}ms vs wait={med_wait:.0f}ms]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
