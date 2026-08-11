"""set_live_view: the write that brings the mirror back down.

libgphoto2 enters live view as a side effect of the first preview capture and leaves
it engaged until the viewfinder widget is cleared, so leaving it is something SEW has
to do explicitly. These cover the paths that decide whether that write happens at all.
"""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from solareclipseworkbench import camera as camera_module
from solareclipseworkbench.camera import (
    VirtualCamera,
    reset_live_view_widget_cache,
    set_live_view,
)


class _FakeCamera:
    def __init__(self, name="Canon EOS 80D"):
        self.name = name
        self._camera = object()


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_live_view_widget_cache()
    yield
    reset_live_view_widget_cache()


def test_writes_the_widget_the_body_exposes():
    writes = []

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
                return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config",
                side_effect=lambda t, name, w, c: writes.append(name) or 0),
          patch("solareclipseworkbench.camera.gp.gp_widget_get_value", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_widget_set_value",
                side_effect=lambda w, v: writes.append(v) or 0)):

        assert set_live_view(_FakeCamera(), True) is True

    assert writes == [1, "eosviewfinder"]


def test_falls_back_to_the_generic_widget_name():
    # The 80D exposes 'viewfinder', not the EOS-specific name tried first.
    def _get_single_config(target, name, context):
        if name == "eosviewfinder":
            raise RuntimeError("no such widget")
        return object()

    written = []

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
                side_effect=_get_single_config),
          patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config",
                side_effect=lambda t, name, w, c: written.append(name) or 0),
          patch("solareclipseworkbench.camera.gp.gp_widget_get_value", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_widget_set_value", return_value=0)):

        assert set_live_view(_FakeCamera(), False) is True

    assert written == ["viewfinder"]


def test_matches_the_value_type_the_widget_already_holds():
    """Drivers type the toggle as int or str; guessing wrong is a silent no-op."""
    written = []

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
                return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_widget_get_value", return_value="0"),
          patch("solareclipseworkbench.camera.gp.gp_widget_set_value",
                side_effect=lambda w, v: written.append(v) or 0)):

        set_live_view(_FakeCamera(), True)

    assert written == ["1"]


def test_probes_once_and_then_stops_touching_usb_on_a_body_without_the_widget():
    """A failed lookup per frame would be a USB round-trip per second, on the
    camera that is about to shoot."""
    lookups = []

    def _get_single_config(target, name, context):
        lookups.append(name)
        raise RuntimeError("no such widget")

    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
                side_effect=_get_single_config)):

        camera = _FakeCamera(name="Nikon D850")
        assert set_live_view(camera, True) is False
        assert set_live_view(camera, False) is False

    assert lookups == ["eosviewfinder", "viewfinder"]


def test_is_a_no_op_on_the_simulator():
    with patch("solareclipseworkbench.camera.gp.gp_context_new") as context_new:
        assert set_live_view(VirtualCamera(), False) is False

    assert not context_new.called


def test_the_kill_switch_stops_every_write():
    with (patch.object(camera_module, "LIVE_VIEW_EXPLICIT_CONTROL", False),
          patch("solareclipseworkbench.camera.gp.gp_context_new") as context_new,
          patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config") as write):

        assert set_live_view(_FakeCamera(), True) is False

    assert not context_new.called
    assert not write.called


def test_never_raises_when_the_driver_misbehaves():
    with (patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
          patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
          patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
                return_value=object()),
          patch("solareclipseworkbench.camera.gp.gp_widget_get_value", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_widget_set_value", return_value=0),
          patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config",
                side_effect=RuntimeError("USB fell over"))):

        assert set_live_view(_FakeCamera(), False) is False
