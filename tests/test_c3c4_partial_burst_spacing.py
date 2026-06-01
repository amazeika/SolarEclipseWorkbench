"""The first C3-C4 partial must clear the post-C3 contact bursts.

take_burst releases the camera right after firing (frames flush in the
background), but a single shot scheduled immediately behind a burst still
collides with its USB teardown -- Partial C3-C4 #1 at the default C3+10 s is
only 2 s after the +8 s Baily's beads burst and hit -110. The wizard now starts
the partial sequence a proven-safe gap after the last burst (the C2 Prominences
shot fires 5 s after the C2 diamond burst without issue), i.e. ~C3+13 s when the
bursts are enabled, and keeps the original C3+10 s when there are none.

Drives the real SummaryPage._generate_script with a mock wizard.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.wizard import SummaryPage

# Poza de la Sal, 2026-08-12 (the 70D reference config).
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
            return _offset_seconds(line.split(",")[3].strip())
    raise AssertionError("no 'Partial C3-C4 #1' shot found in script")


def test_first_partial_cleared_past_the_beads_burst(_qapp):
    # +8 s beads burst + 5 s proven-safe gap => first partial at C3+13 s.
    assert _first_c3c4_offset(_generate(diamond=True, bailys=True)) == 13.0


def test_first_partial_unchanged_without_bursts(_qapp):
    # No post-C3 bursts -> nothing to clear -> original C3+10 s start.
    assert _first_c3c4_offset(_generate(diamond=False, bailys=False)) == 10.0


def test_all_burst_gaps_meet_minimum_so_no_warning(_qapp):
    # Every burst-adjacency in the default 70D script clears MIN_POST_BURST_GAP_S
    # (C2 pair 6s, C2 diamond->totality 5s, C3 pair 7s, C3 beads->partial 5s), so
    # the generation-time guards must emit no warnings.
    script = _generate(diamond=True, bailys=True)
    assert "# WARNING:" not in script


def test_burst_guards_use_the_shared_constant():
    # All four burst-adjacency checks must reference the one source of truth, so
    # the script's safety can't silently drift from the constant.
    from solareclipseworkbench import wizard

    assert wizard.MIN_POST_BURST_GAP_S == 5.0
    # The helper is the single chokepoint for the rule.
    assert wizard._burst_gap_warning(5.0, "a", "b") is None       # at minimum: ok
    assert wizard._burst_gap_warning(4.0, "a", "b") is not None   # below: warns
    assert '"a"' in wizard._burst_gap_warning(4.0, "a", "b")
    assert '"b"' in wizard._burst_gap_warning(4.0, "a", "b")


def test_guards_fire_when_minimum_raised_above_layout(monkeypatch, _qapp):
    # Raise the required gap above every fixed gap in the script (max is the 7s
    # C3 pair) and confirm warnings appear for all four adjacencies -- proving the
    # guards are live checks, not dead code.
    from solareclipseworkbench import wizard

    monkeypatch.setattr(wizard, "MIN_POST_BURST_GAP_S", 8.0)
    script = _generate(diamond=True, bailys=True)
    warnings = [l for l in script.splitlines() if l.startswith("# WARNING:")]
    # C2 pair (6s), C2 diamond->totality (5s), C3 pair (7s) all < 8s.
    assert len(warnings) >= 3
    assert any("Pre-C2 beads" in w for w in warnings)
    assert any("C3 diamond ring" in w and "Post-C3 beads" in w for w in warnings)
