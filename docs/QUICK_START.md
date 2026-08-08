# Solar Eclipse Workbench — Quick Start Guide

This guide walks you from building a photography script to a scheduled,
automated eclipse session in a few minutes. For the full reference, see the
[README](../README.md); for the script-building wizard, see the
[Configuration Wizard Guide](WIZARD_GUIDE.md).

## Contents

1. [What you need](#what-you-need)
2. [1. Build a script with the wizard](#1-build-a-script-with-the-wizard)
3. [2. Launch the workbench](#2-launch-the-workbench)
4. [3. Fill in the toolbar, left to right](#3-fill-in-the-toolbar-left-to-right)
5. [4. Load your script and let it run](#4-load-your-script-and-let-it-run)
6. [Practise first with simulation mode](#practise-first-with-simulation-mode)
7. [After the eclipse: check the shot report](#after-the-eclipse-check-the-shot-report)
8. [Next steps](#next-steps)

## What you need

- The workbench installed and run at least once with an internet connection (it
  downloads ephemeris and timing data on first launch — do this **before**
  eclipse day). See [Installation](../README.md#installation-instructions).
- A USB-connected camera supported by [gphoto2](http://gphoto2.org/) (optional —
  you can practise in simulation mode without one).
- Your observing location's longitude, latitude, and altitude, and the date of
  the eclipse.

## 1. Build a script with the wizard

A *script* is a plain TXT file listing the shots to take, each timed relative to
the eclipse's reference moments (C1, C2, MAX, C3, C4). The easiest way to create
one is the configuration wizard. From the repo root, run:

```bash
uv run sew_wizard
```

The wizard steps you through a few pages and writes a ready-to-use script at the
end:

1. **Eclipse & location** — pick your eclipse from the drop-down (the next 20 are
   listed) and choose a saved location or enter custom longitude/latitude/
   altitude. You can save locations to reuse them next time.
2. **Equipment** — select or configure your camera. Enter the **exact** camera
   name as recognised by the camera system, your lens/telescope focal length and
   aperture range, and your solar filter's ND value. These drive the automatic
   exposure calculations.
3. **ISO & options** — set a preferred ISO (400 is a good default) and a
   bracketing range, optionally enable voice prompts and periodic camera sync
   (battery/storage checks).
4. **Phenomena** — tick which events to photograph: C1/C4 contacts, equispaced
   partial-phase shots, diamond rings (C2/C3), Baily's beads, chromosphere, and
   the corona. For partial phases you choose an interval by magnitude (e.g. every
   2%) or by time (e.g. every 60 s), and the wizard generates **every**
   intermediate shot with timing, sun altitude, and exposure calculated for you.

When you finish, save the generated script somewhere you can find it. Full
details for every page are in the
[Configuration Wizard Guide](WIZARD_GUIDE.md).

Prefer to hand-write or convert an existing script? See
[Script file format](../README.md#script-file-format) and
[Converting scripts from Solar Eclipse Maestro](../README.md#converting-scripts-from-solar-eclipse-maestro).

## 2. Launch the workbench

From the repo root:

```bash
# Linux or WSL on Windows
uv run sew

# macOS: gphoto2 needs root to reach the cameras
sudo uv run sew
```

You can pass your location and date up front so they're pre-filled:

```bash
uv run sew -d 2024-04-08 -lon -104.63525 -lat 24.01491 -alt 1877.3
```

## 3. Fill in the toolbar, left to right

The toolbar icons must be used **left to right**. Each one populates part of the
top section of the UI:

1. **Location** — enter longitude, latitude, and altitude (or capture them with
   [GPS from your phone](GPS_PHONE.md) or a USB GPS device).
2. **Date** — pick the eclipse date from the drop-down (the next 20 eclipses are
   listed).
3. **Reference moments** — fill in C1/C2/MAX/C3/C4, sunrise, and sunset. This
   needs the location and date set first.
4. **Camera** — update camera status (battery, free memory), sync each camera's
   clock to your computer, and warn if focus/shooting mode isn't Manual.

If you started `sew` with command-line arguments, the location and date are
already filled in — just click Reference moments and Camera.

## 4. Load your script and let it run

1. Click the **File** icon and choose your TXT script.
2. The scheduled jobs appear in the bottom section of the UI, each with a
   countdown and execution time.
3. Leave the workbench running. Each shot fires automatically at its scheduled
   moment.

Optional during the run: open **Live View** (rightmost toolbar button) to
confirm the Sun stays framed and in focus. It auto-pauses around totality so it
never competes with scheduled shots for the USB bus.

To stop everything, press the **Stop** icon — use it with caution, as it shuts
down the scheduler and clears the job list.

## Practise first with simulation mode

You don't need a real eclipse — or even a camera — to rehearse. Start in
simulation mode and choose when, relative to a reference moment, the run should
begin:

```bash
# With a connected camera
sudo uv run sew -s            # macOS
uv run sew -s                 # Linux / WSL

# With no camera at all
uv run sew -s --virtual-camera
```

A **Simulation** icon appears in the toolbar; use it to set the simulated start
time before loading your script. Rehearse the full sequence so there are no
surprises on eclipse day.

## After the eclipse: check the shot report

Every run writes a per-run CSV report next to the log, recording each scheduled
shot and whether it actually fired. Missed shots are highlighted in the UI so
you can spot problems at a glance. See
[Missed-shot indicator and shot report](../README.md#missed-shot-indicator-and-shot-report).

## Next steps

- [README](../README.md) — complete reference for every feature and command-line
  option.
- [Troubleshooting Guide](TROUBLESHOOTING.md) — what to do when something goes
  wrong, including recovering from a crash mid-eclipse.
- [Configuration Wizard Guide](WIZARD_GUIDE.md) — building and tuning scripts.
- [GPS from your phone](GPS_PHONE.md) — capturing precise coordinates in the
  field.
