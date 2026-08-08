# Eclipse Day — Field Checklist

What to do, when to do it, and what to leave alone. Written around the
`Total_Solar_Eclipse_2026_20260807.txt` script — 12 August 2026, Páramo de Poza
de la Sal, Canon EOS 80D at 382 mm f/4.7 behind an ND5 solar filter. Every time
below is read off that script; adapt the numbers for a different run.

Print this. The laptop shows the schedule, but you want paper in your pocket.

For the normal setup sequence see the [Quick Start Guide](QUICK_START.md); when
something breaks, go to the [Troubleshooting Guide](TROUBLESHOOTING.md).

## Contents

1. [Read the clock right](#read-the-clock-right)
2. [Reference moments for this run](#reference-moments-for-this-run)
3. [The day before](#the-day-before)
4. [Camera settings that must be right](#camera-settings-that-must-be-right)
5. [Setting up on site](#setting-up-on-site)
6. [Focus and framing schedule](#focus-and-framing-schedule)
7. [Filter off, filter on](#filter-off-filter-on)
8. [Hands off: C2 − 25 s to C3 + 25 s](#hands-off-c2--25-s-to-c3--25-s)
9. [Expected, not faults](#expected-not-faults)
10. [After the last frame](#after-the-last-frame)

---

## Read the clock right

**The `@ HH:MM:SS` comments in the script are UTC.** Spain in August is CEST,
UTC+2, so everything happens two hours later on your watch than the script says.
The jobs table in the workbench shows both — *Execution time (local)* and
*Execution time (UTC)* — and so does every table below. Work from the local
column in the field and never mix the two.

The whole schedule hangs off your computer's clock. There is no mains power and
probably no mobile data on the páramo, so NTP will not save you there:

- Sync the laptop clock over the internet **before you leave**.
- On site, cross-check against GPS — [GPS from your phone](GPS_PHONE.md) or a USB
  GPS device — and enter any residual offset in the **Location** pop-up. That
  offset is applied to every scheduled job and is still accepted while a script
  is loaded.

A five-second clock error is the difference between a diamond ring and a blank
white frame.

---

## Reference moments for this run

Computed for 42.67005° N, 3.57468° W, 1090 m. Magnitude 1.009, totality
**1 min 34 s**.

| Moment | Local (CEST) | UTC | Sun alt | Sun az |
|---|---|---|---|---|
| C1 — first contact | **19:32:50** | 17:32:50 | 18.4° | 273° |
| First partial frame (#1) | 19:33:00 | 17:33:00 | 18.4° | |
| Last **filtered** frame (#50) | **20:26:42** | 18:26:42 | 8.6° | |
| Pre-C2 beads burst (unfiltered) | 20:27:49 | 18:27:49 | 8.4° | |
| C2 — totality begins | **20:27:57** | 18:27:57 | 8.4° | 282° |
| HDR burst starts (MAX − 13 s) | 20:28:32 | 18:28:32 | 8.3° | |
| MAX | 20:28:45 | 18:28:45 | 8.3° | 283° |
| C3 — totality ends | **20:29:32** | 18:29:32 | 8.1° | 283° |
| Post-C3 beads burst (unfiltered) | 20:29:40 | 18:29:40 | 8.1° | |
| "Filters on" voice prompt | 20:29:52 | 18:29:52 | 8.1° | |
| Last frame of the run (#45) | 21:14:53 | 19:14:53 | 0.1° | |
| Sunset | 21:20:27 | 19:20:27 | — | 291° |
| C4 | 21:21:12 | 19:21:12 | −1.0° | 291° |

The sun sets 45 s *before* C4, which is why the script skips it. The run is
1 h 42 m from C1 to the last frame, and fires roughly 165 frames (50 filtered
partials, 45 more after C3, 23 totality singles, a 15-shot HDR, four one-second
bursts, three at C1).

**Scout your western horizon.** The sun tracks from azimuth 273° to 291° and
drops from 18° to the horizon. Totality happens at only 8° altitude, so anything
on the WNW skyline — a ridge, a treeline — eats the end of the sequence. Check
this on a daylight visit, not at 20:00 on the day.

---

## The day before

- [ ] Run the workbench once **with internet** so ephemeris and timing data are
      downloaded and cached. It will not do this on the páramo.
- [ ] Rehearse the whole script in simulation mode (`uv run sew -s`) so nothing
      about the sequence is new to you.
- [ ] Sync the laptop clock.
- [ ] Install and test [caffeine](https://www.caffeine-app.net/) so the computer
      does not sleep mid-eclipse.
- [ ] Charge the camera battery **and** the laptop; charge a spare.
- [ ] Format the card in the camera. ~5 GB of RAW is coming; give it far more.
- [ ] Write the relaunch command on paper and tape it to the laptop:

      sudo uv run sew -lat 42.67005 -lon -3.57468 -alt 1090 -d 2026-08-12

  **`-d` is the part that matters.** Opening a script reads the location from its
  `# Coordinates:` header, recomputes the contact times for it, and then locks
  the Location pop-up — so the coordinates on that line are belt-and-braces and
  get overwritten anyway. The eclipse *date* is in no header the app reads. Set
  no date and the script does not load at all: you get *Reference Moments Not
  Set* and a refusal. The date normally restores from
  `~/.SolarEclipseWorkbench.ini`, but on macOS you must run under `sudo` for
  gphoto2, and `sudo` may resolve `~` to root's home rather than yours — in which
  case it silently does not restore, and you find out at the file dialog. Type
  the whole line rather than working out which arguments you need in the dark.

- [ ] Pack: solar viewing glasses, red torch, gaffer tape, spare USB cable,
      tripod weight (it is an exposed plateau at 1090 m — it will be windy), and
      a warm layer for the temperature drop.

**Start the run on a fresh battery.** Swapping one mid-sequence drops the USB
session and costs you a relaunch plus a re-detect. The tethered session with
occasional live view will drain an 80D over 1 h 42 m, so a dummy battery on
mains, if you have one, is the safer choice.

---

## Camera settings that must be right

The workbench sets aperture, shutter and ISO per shot, and it handles drive mode
around the bursts by itself. Everything below it does *not* set for you:

| Setting | Value | Why |
|---|---|---|
| Mode dial | **M** | The app warns if it is not, but fix it before it matters |
| Lens switch | **MF** | Autofocus will hunt on a filtered sun and lose the shot |
| Image stabiliser | **Off** | It fights the tripod |
| Long-exposure noise reduction | **Off** | Non-negotiable — LENR doubles the time a frame occupies the camera, and the 2 s earthshine and 1 s corona frames would push everything after them into the missed pile |
| High-ISO noise reduction | Off | Same reason, smaller effect |
| Image review | Off | Saves power and bus time |
| Auto power-off | Disable | Stops the body sleeping during setup |
| Format | RAW | You will want the latitude on the corona frames |

The camera name in the script must match what the workbench detects, character
for character — `Canon EOS 80D`. If it does not, the script loads with voice
prompts and **no photo jobs**. Check the Camera(s) overview table before you load
it.

---

## Setting up on site

Work backwards from C1 at 19:32:50 local. Aim to have everything below finished
by **19:00**, which leaves half an hour of slack and time to just look at the
sky.

1. **Tripod and mount** — level, weighted, pointed WNW. If you are tracking,
   align now; if not, accept that you will re-centre by hand and plan for it in
   the windows below.
2. **Filter on before you point at the sun.** Check it for pinholes against a
   bright sky first, and make sure it cannot be knocked off by wind — tape it if
   the fit is loose.
3. **Laptop** — caffeine on, camera plugged in, screen brightness up.
4. **Toolbar, left to right**: Location → Date → Reference moments → Camera(s).
   The relaunch command above pre-fills the first two.
5. **Check the reference moments against the table on page one.** If C2 does not
   read 20:27:57 local, stop and fix the location or the date before going
   further.
6. **Load the script.** Confirm the jobs table fills with photo jobs, not just
   voice prompts, and that the first one counts down to 19:32:48.
7. **Baseline focus** — see below. Do this before C1, while you still have all
   the time in the world.

---

## Focus and framing schedule

Four windows, and then you stop. Combine focus and framing in each — if you are
on a static tripod, re-centre the sun first, then check focus.

Every window sits in a gap between scheduled frames. Live view steps aside when
a camera job is within about 8 s, so it will simply refuse to open if you are
late; the end times below already leave that margin. None of them collide with
the camera-sync jobs either.

| # | Window (local) | Window (UTC) | Sits between | Purpose |
|---|---|---|---|---|
| 1 | **before 19:32:30** | before 17:32:30 | — nothing scheduled yet | Establish critical focus |
| 2 | **19:49:28 – 19:50:24** | 17:49:28 – 17:50:24 | frames #16 and #17 | First thermal-drift check |
| 3 | **20:05:54 – 20:06:50** | 18:05:54 – 18:06:50 | frames #31 and #32 | Mid-partial check |
| 4 | **20:23:26 – 20:24:22** | 18:23:26 – 18:24:22 | frames #47 and #48 | **Final focus** |
| — | 20:24:32 – 20:25:28 | 18:24:32 – 18:25:28 | frames #48 and #49 | Fallback, confirm only |

**Window 1 — the real one.** Nothing is scheduled until the C1 − 2 s frame, so
take as long as you need. The sun is at 18.4°, the highest it will be all
afternoon, which means the best seeing you will get. Use 10× live view on a
sunspot or the solar limb. This is where focus is *set*; the rest are checks.

**Window 2** is ~17 minutes after C1, once the lens has equilibrated to sitting
in the sun under the filter. This is where the first genuine drift shows up.

**Window 3** is around 50% obscuration. The moon's limb crossing the disc gives
you a far higher-contrast focus target than the solar limb alone — use it.

**Window 4** is the last one worth planning, at C2 − 4:31 to C2 − 3:35. It closes
more than two minutes before you need your hands on the filter, which is the
point. Take the fallback window only to confirm what window 4 told you.

Then tape the focus ring and walk away.

Two things shape this schedule:

- **Do not chase focus late.** The sun falls from 18.4° at C1 to 8.4° at C2. By
  window 4 the image will be boiling in the low-altitude seeing, and live view
  will lie to you. Windows 2–4 exist to detect *thermal drift* against the focus
  you set in window 1 — small nudges only. If window 4 disagrees wildly with
  window 3, distrust window 4 and leave it alone.
- **Live view costs battery and bus time.** Four short windows is not
  conservatism, it is the budget.

Because you are not refocusing after window 4: tape the focus ring, confirm MF
and IS are still off, and **do not power-cycle the body**. A focus-by-wire lens
(STM, nano-USM) loses its focus position the moment the camera powers down. Also
re-check framing after touching the barrel — it is easy to nudge the rig while
taping it.

There is no focus voice prompt in the workbench, only `filters_on`. **Set phone
alarms for 19:49, 20:05 and 20:23 local.**

One thing the app *does* give you free: the camera-sync jobs at 19:48, 20:03,
20:17, 20:45, 21:00 and 21:14 local refresh battery and free-memory readings in
the UI. Glance at the battery figure each time.

---

## Filter off, filter on

This is the highest-risk minute of the day. Rehearse the hand movements at home
until they are automatic.

**Filter off.** You have a 67-second window between the last filtered frame and
the first unfiltered one:

| Local | What |
|---|---|
| 20:25:57 | "C2 in 2 minutes" — get into position, hands ready, do not touch yet |
| 20:26:42 | Frame #50 fires. **This is your cue.** It needs the filter on |
| 20:26:45 – 20:27:00 | Filter off. Do it now, calmly |
| 20:26:57 | "C2 in 60 seconds" — you should already be done |
| 20:27:40 | Hands completely clear of the rig |
| 20:27:49 | Pre-C2 beads burst fires unfiltered |

Removing a **front-mounted** filter introduces no focus shift — it sits in
collimated light. If yours lives in a rear filter drawer instead, it *will* shift
the focal plane by roughly a third of the glass thickness, which at f/4.7 is
several times your depth of focus. Confirm which you have before the day; if it
is a rear filter, window 4 is worthless and you need a pre-calibrated offset
instead.

**Filter on.** Tighter, and the script does not leave you room to be tidy:

| Local | What |
|---|---|
| 20:29:32 | C3. Totality is over |
| 20:29:40 | Post-C3 beads burst fires — the last unfiltered frame |
| 20:29:41 | **Filter on immediately.** Do not wait for the voice prompt |
| 20:29:45 | Partial C3–C4 #1 fires — you will not have made it. See below |
| 20:29:52 | "Filters on" voice prompt — a backstop, not your cue |
| 20:30:46 | Partial C3–C4 #2 — this one should be clean |

An unfiltered 382 mm lens on the sun is hard on the shutter even at 8° altitude.
Getting the filter back on beats saving frame #1.

---

## Hands off: C2 − 25 s to C3 + 25 s

From **20:27:33 to 20:29:57 local** the workbench locks live view out
deliberately — the filter is off and the mirror must stay down. That is also your
own rule: do not touch the rig, do not chimp, do not adjust anything.

Ninety-four seconds is not long. The script is firing 23 single frames, a
15-shot HDR and two bursts in that time, and there is nothing you can usefully
add. **Look at it with your own eyes.** That is what the automation is for.

---

## Expected, not faults

Do not react to any of these in the field.

- **Partial C3–C4 #1 at 20:29:45 will be blown out.** It is scheduled 13 s after
  C3 at a filtered exposure, and no human gets the filter on that fast. One frame
  out of 165. Ignore it.
- **The `Missed: N` counter will probably be non-zero after totality.** The
  corona sequence is spaced at 2 s, which is exactly the workbench's minimum for
  normal mode, so the 80D may not keep up with every frame. Corona #10, about a
  second after the HDR burst ends, is the most likely casualty. A shot that
  cannot start within 1.5 s is skipped rather than fired late, which protects
  everything after it. There is nothing to fix mid-eclipse.
- **The last few C3–C4 frames will be poor.** #45 fires at 0.1° altitude, five
  minutes before sunset, through the whole thickness of the atmosphere. Refraction
  and horizon haze, not focus, are what you are seeing.
- **C4 is never photographed.** The sun is below the horizon by then, and the
  script says so in its closing comment.

If something genuinely breaks — a crash, a camera that will not claim, a script
that loads with no jobs — go straight to the
[Troubleshooting Guide](TROUBLESHOOTING.md). The recovery is: relaunch, click
Camera(s), reload the script, in that order. Past jobs are dropped silently, so
you lose only what was due while you were down.

---

## After the last frame

The run ends at 21:14:53 local. Before you break anything down:

- Leave the camera connected and the app running until you have confirmed the
  card has what you expect.
- **Treat the card as the primary copy.** Anything the app downloaded went to
  `~/Pictures/SolarEclipseWorkbench` — under `sudo` that is *root's* home
  directory, not yours.
- Copy the per-run report `<timestamp>.shots.csv` and the log
  `solareclipseworkbench-<user>.log` out of your temporary directory. The log is
  overwritten on the next launch.
- Back the card up before you sleep, then again before you drive home.

The shot report tells you exactly which frames fired and which were skipped —
that is the honest record of the run, and it is worth reading before you start
judging the images. See
[Missed-shot indicator and shot report](../README.md#missed-shot-indicator-and-shot-report).
