"""Unit tests for `dedupe_cameras_by_serial`.

libgphoto2 sometimes reports a single physical camera twice (a real port plus a
phantom on a bogus bus such as ``usb:000,001``).  The helper collapses entries
that share a serial number while never dropping a possibly-distinct camera.

These tests inject fake `open_fn`/`serial_fn` callables, so no camera or
libgphoto2 backend is required.
"""

import pytest

from solareclipseworkbench.camera import dedupe_cameras_by_serial


class _FakeCam:
    """Minimal stand-in for a camera adapter: records whether it was closed."""

    def __init__(self, port):
        self.port = port
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def _make_fns(serial_by_port, *, raise_on=()):
    """Build (open_fn, serial_fn, opened) for a port→serial mapping.

    `raise_on` is a set of ports for which `open_fn` raises (camera won't open).
    `opened` collects the cams that were opened, so tests can assert they close.
    """
    opened = []

    def open_fn(model, port):
        if port in raise_on:
            raise RuntimeError(f"cannot open {port}")
        cam = _FakeCam(port)
        opened.append(cam)
        return cam

    def serial_fn(cam):
        return serial_by_port.get(cam.port)

    return open_fn, serial_fn, opened


def test_same_serial_collapses_to_one():
    """One physical camera on two ports (same serial) → a single entry."""
    detected = [("Canon EOS 80D", "usb:001,001"), ("Canon EOS 80D", "usb:000,001")]
    open_fn, serial_fn, _ = _make_fns(
        {"usb:001,001": "123456789103", "usb:000,001": "123456789103"}
    )

    result = dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    assert result == [("Canon EOS 80D", "usb:001,001")]


def test_distinct_serials_are_kept():
    """Two genuinely different bodies (distinct serials) → both kept."""
    detected = [("Canon EOS 80D", "usb:001,005"), ("Canon EOS 80D", "usb:001,007")]
    open_fn, serial_fn, _ = _make_fns(
        {"usb:001,005": "AAA", "usb:001,007": "BBB"}
    )

    result = dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    assert result == detected


def test_unreadable_serial_entry_is_kept():
    """An entry whose serial cannot be read is never collapsed away."""
    detected = [("Canon EOS 80D", "usb:001,001"), ("Generic PTP", "usb:001,009")]
    open_fn, serial_fn, _ = _make_fns(
        {"usb:001,001": "123456789103", "usb:001,009": None}
    )

    result = dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    assert result == detected


def test_open_failure_keeps_entry_and_does_not_raise():
    """If a camera will not open, its entry is kept (treated as distinct)."""
    detected = [("Canon EOS 80D", "usb:001,001"), ("Canon EOS 80D", "usb:000,001")]
    open_fn, serial_fn, _ = _make_fns(
        {"usb:001,001": "123456789103"}, raise_on={"usb:000,001"}
    )

    result = dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    # The phantom won't open here, so it can't be proven a duplicate → kept.
    assert result == detected


def test_phantom_first_keeps_real_bus_port():
    """When the phantom (bus 000) is listed first, the real-bus port is kept."""
    detected = [("Canon EOS 80D", "usb:000,001"), ("Canon EOS 80D", "usb:001,001")]
    open_fn, serial_fn, _ = _make_fns(
        {"usb:000,001": "123456789103", "usb:001,001": "123456789103"}
    )

    result = dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    assert result == [("Canon EOS 80D", "usb:001,001")]


def test_opened_cameras_are_closed():
    """Every camera opened to read its serial is disconnected afterwards."""
    detected = [("Canon EOS 80D", "usb:001,001"), ("Canon EOS 80D", "usb:000,001")]
    open_fn, serial_fn, opened = _make_fns(
        {"usb:001,001": "123456789103", "usb:000,001": "123456789103"}
    )

    dedupe_cameras_by_serial(detected, open_fn=open_fn, serial_fn=serial_fn)

    assert opened and all(cam.disconnected for cam in opened)
