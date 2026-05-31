"""The first C3-C4 partial shot must clear the Post-C3 beads burst flush.

With the burst drain-until-idle fix, a Canon burst holds the camera through its
multi-second card flush. The Post-C3 beads burst is at C3+8s, so the C3-C4
partial sequence must not start at the old C3+10s (it lands in the flush window
and is dropped). When the diamond/Baily's bursts are enabled the first partial
is pushed past the burst; when they are not, it stays at the original offset.

Drives the real SummaryPage._generate_script with a mock wizard, so it exercises
the actual generation path (the root-level test_*_generation scripts only
re-implement the algorithm).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.wizard import SummaryPage

# Poza de la Sal, 2026-08-12 (the 70D reference config); 94 s totality.
_BASE_FIELDS = {
    'altitude': 851.0, 'aperture_max': 4.7, 'aperture_min': 4.7, 'bailys': True,
    'c1_c4': True, 'camera_name': 'Canon EOS 70D', 'chromosphere': True, 'corona': True,
    'diamond': True, 'earthshine': True, 'eclipse_date': '2026-08-12',
    'eclipse_name': 'Total Solar Eclipse 2026', 'eclipse_type': 'Total', 'equispaced': True,
    'filter_manual': False, 'filter_value': 5.0, 'focal_length': 382, 'hdr_burst': True,
    'hdr_iso_auto': True, 'hdr_iso_manual': 400, 'hdr_start_auto': True,
    'hdr_start_speed': '1/1250', 'hdr_stops': 7, 'iso_max': 1600, 'iso_min': 100,
    'latitude': 42.65509, 'location': 'Poza de la Sal', 'longitude': -3.52397,
    'magnitude_value': 2.0, 'partial_magnitude': True, 'preferred_iso': 400,
    'prominences': True, 'seconds_value': 60, 'sync_enabled': False, 'sync_interval': 15,
    'voice_basic': True, 'voice_enabled': True,
}


@pytest.fixture(scope="module")
def _qapp():
    return QApplication.instance() or QApplication([])


def _offset_seconds(offset_str):
    h, m, s = offset_str.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _generate(**overrides):
    fields = {**_BASE_FIELDS, **overrides}

    class _Wiz:
        def field(self, key):
            return fields[key]

    page = SummaryPage.__new__(SummaryPage)
    page.wizard = lambda: _Wiz()
    return page._generate_script()


def _first_c3c4_offset(script):
    for line in script.splitlines():
        if line.startswith("take_picture") and "Partial C3-C4 #1 " in line:
            # take_picture, C3, +, <offset>, ...
            return _offset_seconds(line.split(",")[3].strip())
    raise AssertionError("no 'Partial C3-C4 #1' shot found in script")


def test_first_partial_clears_post_c3_beads_burst(_qapp):
    # Post-C3 beads burst is at C3+8s; the first partial must start after it
    # has flushed (well past +10s), so it fires instead of dropping.
    offset = _first_c3c4_offset(_generate(diamond=True, bailys=True))
    assert offset >= 25.0, f"first C3-C4 partial at +{offset}s, still in the burst window"


def test_first_partial_unchanged_without_bursts(_qapp):
    # No post-C3 bursts -> nothing to dodge -> original C3+10s start.
    offset = _first_c3c4_offset(_generate(diamond=False, bailys=False))
    assert offset == 10.0, f"expected +10s without bursts, got +{offset}s"
