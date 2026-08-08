# Troubleshooting

Things that go wrong, and what to do about them. The first section is the one
you want on eclipse day — the rest is ordered by when in the session a problem
shows up.

For the normal happy-path sequence, see the [Quick Start Guide](QUICK_START.md);
for what to do and check on site, see the
[Eclipse Day Field Checklist](ECLIPSE_DAY.md).

## Contents

1. [The app crashed or closed mid-eclipse](#the-app-crashed-or-closed-mid-eclipse)
2. [At startup](#at-startup)
3. [Detecting cameras](#detecting-cameras)
4. [Loading the script](#loading-the-script)
5. [During the run](#during-the-run)
6. [Where the files are](#where-the-files-are)

---

## The app crashed or closed mid-eclipse

**Relaunch it, click Camera(s), then load your script again.** That is the whole
procedure. Do it in that order.

Shots whose moment has already passed are *not* fired late and do not pile up —
each job is scheduled at an absolute date and time, so on reload the ones in the
past are dropped silently and never appear in the jobs table. Everything still
in the future is scheduled normally. You lose only what was due while the app was
down.

To take the guesswork out of the relaunch, pass your location and eclipse date on
the command line — that way the reference moments are computed at startup without
depending on the saved settings file:

```bash
# macOS
sudo uv run sew -lat 42.67005 -lon -3.57468 -alt 1090 -d 2026-08-12

# Linux or WSL on Windows
uv run sew -lat 42.67005 -lon -3.57468 -alt 1090 -d 2026-08-12
```

Substitute your own coordinates and date. Write this line down before eclipse day
so you are not composing it under pressure.

If the camera will not connect on the second attempt, see
[Detecting cameras](#detecting-cameras) — a crashed process can leave the USB
device claimed.

> **Note:** relaunching overwrites the application log from the crashed run. If
> you want to know afterwards *why* it crashed, copy
> `solareclipseworkbench-<user>.log` out of your temporary directory before
> restarting — but only if you can spare the seconds. Getting back up matters more.
> The shot report CSV is per-run and is never overwritten.

The same procedure applies after you press **Stop**: it shuts down the scheduler
and clears the job list, so reload the script to resume.

---

## At startup

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Reference-moment fields (C1…C4, sunrise, sunset) are empty | Location and eclipse date were not restored from the settings file | Click **Location**, then **Date**, then **Reference moments** — or relaunch with `-lat -lon -alt -d` |
| Settings you saved earlier are missing on macOS | Settings live in `~/.SolarEclipseWorkbench.ini`, and under `sudo` the home directory may resolve to root's rather than yours | Pass `-lat -lon -alt -d` on the command line, or click **Save** once while running under `sudo` so the values are stored where that run will find them |
| First launch hangs or errors on ephemeris data | No internet connection | Run the app once with internet **before** eclipse day; it downloads ephemeris and timing data on first launch |

---

## Detecting cameras

Clicking **Camera(s)** connects to each camera, syncs its clock to the computer,
and warns about settings that would ruin the sequence. Do this before loading the
script.

### `Cannot claim USB device` / gphoto2 error −53

Another process is holding the camera. This is the most common failure after a
crash, because the operating system grabs the device the moment the app lets go.

- **macOS** — quit Image Capture and Sony Imaging Edge, then:
  ```bash
  sudo pkill -9 PTPCamera
  ```
  If that does not clear it: unplug and replug the camera, then power-cycle the
  camera body.
- **Linux** — a stale `gphoto2` process or `gvfs-gphoto2-volume-monitor` may hold
  the device. Check with `gphoto2 --auto-detect` and kill the conflicting process.
- **Windows / WSL** — Windows keeps its PTP/WIA driver active even after
  `usbipd attach`. Replace it with WinUSB using Zadig, then detach and re-attach.
  Full instructions are in the
  [README](../README.md#replace-the-windows-usb-driver-with-winusb-required-for-gphoto2).

**Sony bodies** additionally need PC Remote enabled on the camera itself:
Menu → Network → PC Remote Settings → PC Remote → **On**.

### Warnings about focus or shooting mode

The app warns when a camera's focus mode or shooting mode is not Manual. Set the
lens switch to **MF** and the mode dial to **M**. Autofocus will hunt on a
filtered Sun and cost you the shot.

### Sony: images not on the card, or timing slipping

Set **PC Remote Settings → Save Destination** to **PC+Camera** (or **Camera
Only**). This keeps images on the SD card and preserves tight shot timing.

---

## Loading the script

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Warning: *Reference Moments Not Set*, script refuses to load | No eclipse date is set, so contact times could not be computed | Set the **Date** (and **Location**) first, then load the script — or relaunch with `-lat -lon -alt -d` |
| Warning: *No Jobs Scheduled* | The camera name in the script does not match a detected camera — or you loaded the script before clicking **Camera(s)** | Compare the names in the script against the Camera(s) overview table; they must match exactly. Press **Stop**, click **Camera(s)**, then load again |
| Voice prompts are scheduled but no photos | Same as above: photo jobs are skipped when their camera name cannot be resolved | As above |
| The **Camera(s)** button is greyed out | A script is loaded; the camera set is fixed for the run | Press **Stop** to unlock it, then reload the script afterwards |
| Message: *Location loaded from script* | Normal. The observing location is taken from the script header and the reference moments are recomputed for it | Nothing to do — this is what keeps the schedule aligned with the script |
| Message: *Location locked to script* when using the Location pop-up | Normal. While a script is loaded its header coordinates are authoritative | To observe from elsewhere, press **Stop** and load a script generated for that location. A GPS time offset entered here is still applied |

---

## During the run

### The `Missed: N` counter turns red

A shot that cannot start within 1.5 s of its scheduled time is skipped rather
than fired late, to protect the timing of the rest of the sequence. Skipped rows
turn red in the jobs table and the counter breaks the total down per camera.

If the counter climbs, your shots are spaced more tightly than that body can keep
up with. There is nothing to fix mid-eclipse — note it and widen the spacing (or
use a faster body for the dense sections) next time. See
[Missed-shot indicator and shot report](../README.md#missed-shot-indicator-and-shot-report).

### Live view is greyed out or will not open

This is deliberate in three cases:

- **Around totality** — live view is locked out from 25 s before C2 until 25 s
  after C3. The solar filter is off during that window and the mirror must stay
  down.
- **Just before a scheduled shot** — live view steps aside when a camera job is
  within about 8 s, so it never competes for the USB bus.
- **Turned off in Settings** — check Settings → Datetime format.

A partial eclipse has no C2 or C3, so the totality lockout never applies.

### The computer falls asleep

It will, unless you stop it. Use [caffeine](https://www.caffeine-app.net/) on
macOS and Linux, or [PowerToys Awake](https://awake.den.dev/) on Windows. Set
this up before the eclipse, not during it.

### Shots fire consistently early or late

Check the GPS time offset in the **Location** pop-up. The offset is applied to
every scheduled time, and it is accepted even while a script is loaded and the
coordinates themselves are locked.

---

## Where the files are

Everything lands in your system temporary directory (`echo $TMPDIR` on macOS,
usually `/tmp` on Linux):

| File | Contents |
|------|----------|
| `solareclipseworkbench-<user>.log` | Application log. **Overwritten on every launch** — copy it aside before relaunching if you need it |
| `<timestamp>.shots.csv` | Per-run shot report, one row per scheduled shot with its outcome. Named for the run start time, so runs never overwrite each other |

Under `sudo` the `<user>` in the log name is `root`.

Images stay on the camera's memory card. Any that the app downloads go to
`~/Pictures/SolarEclipseWorkbench` — under `sudo`, that is root's home directory,
not yours. Treat the card as the primary copy.

For the meaning of each column in the shot report, see
[Per-run CSV report](../README.md#per-run-csv-report).
