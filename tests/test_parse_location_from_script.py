"""parse_location_from_script reads the observing location from a script header.

The wizard writes ``# Coordinates: <lat>° N, <lon>° E, <alt> m`` (latitude first,
signed values). The parser must return (longitude, latitude, altitude) to match
SolarEclipseController.set_location, scan only the header, and degrade to None
rather than misread command lines as coordinates.
"""

from solareclipseworkbench.scripts import parse_location_from_script

HEADER = (
    "# Solar Eclipse Photography Script\n"
    "# Date: 2026-08-12\n"
    "# Location: Poza de la Sal\n"
    "# Coordinates: 42.65509° N, -3.52397° E, 851.0 m\n"
    "# Camera: Canon EOS 70D\n"
    "\n"
    'take_picture, C2, +, 0:00:03.0, Canon EOS 70D, 1/5000, 4.7, 400, "Prominences"\n'
)


def _write(tmp_path, text, name="script.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parses_lon_lat_alt_in_set_location_order(tmp_path):
    lon, lat, alt = parse_location_from_script(_write(tmp_path, HEADER))
    assert (lon, lat, alt) == (-3.52397, 42.65509, 851.0)


def test_handles_mojibake_degree_sign(tmp_path):
    # Some files carry the UTF-8 degree sign decoded as latin-1 ("Â°").
    text = HEADER.replace("°", "Â°")
    lon, lat, alt = parse_location_from_script(_write(tmp_path, text))
    assert (lon, lat, alt) == (-3.52397, 42.65509, 851.0)


def test_integer_altitude_and_positive_longitude(tmp_path):
    text = "# Coordinates: 40° N, 3.5° E, 828 m\n"
    lon, lat, alt = parse_location_from_script(_write(tmp_path, text))
    assert (lon, lat, alt) == (3.5, 40.0, 828.0)


def test_returns_none_when_no_coordinates_header(tmp_path):
    text = "# Date: 2026-08-12\n" 'take_picture, C2, +, 0:00:03.0, cam, 1/5000, 4.7, 400, "x"\n'
    assert parse_location_from_script(_write(tmp_path, text)) is None


def test_stops_at_first_command_line(tmp_path):
    # A "Coordinates:" appearing only after the header (e.g. in a quoted
    # description) must not be picked up.
    text = (
        "# Date: 2026-08-12\n"
        'take_picture, C2, +, 0:00:03.0, cam, 1/5000, 4.7, 400, "Coordinates: 1.0 N, 2.0 E, 3.0 m"\n'
    )
    assert parse_location_from_script(_write(tmp_path, text)) is None


def test_missing_file_returns_none(tmp_path):
    assert parse_location_from_script(str(tmp_path / "does_not_exist.txt")) is None
