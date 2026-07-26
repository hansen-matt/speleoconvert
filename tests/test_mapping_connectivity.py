"""Shots must be emitted in connectivity order, not file order.

Real projects (e.g. MBSP) contain surveys whose starting station is defined in a
later survey or a later .dat. File-order emission created spurious unanchored
START shots, which Ariane renders at (0,0) — 'the star off the west coast of
Africa'.
"""
import pytest

from speleoconvert.compass.model import (
    CompassDatFile,
    CompassProject,
    CompassSurvey,
    DatLink,
    FixedStation,
)
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from tests.test_mapping import FMT, _shot


def _survey(name, shots, source="t.dat"):
    return CompassSurvey(
        cave_name="cave", name=name, date_raw="2 23 2024", comment="",
        team=(), declination_deg=0.0, format=FMT,
        corrections=None, corrections2=None,
        discovery_raw=None, has_backsight_columns=False,
        shots=tuple(shots), source_file=source,
    )


def _project_multi(surveys, fixed=(), base=None):
    return CompassProject(
        mak_path="/tmp/test.mak",
        base_easting_m=base[0] if base else None,
        base_northing_m=base[1] if base else None,
        base_elevation_m=0.0 if base else None,
        base_zone=base[2] if base else None,
        convergence_deg=None,
        datum="WGS 1984", flags_raw=None, comments=(),
        links=(DatLink("t.dat", "WGS 1984", 17, tuple(fixed)),),
        dat_files=(CompassDatFile("t.dat", tuple(surveys)),),
    )


def _all_shots(d):
    return [s for sec in d["sections"] for s in sec["shots"]]


def test_forward_reference_does_not_create_spurious_start():
    # Survey 1 starts at B, but B is only defined by survey 2 (A -> B), A fixed.
    fixed = [FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")]
    prj = _project_multi(
        [_survey("S1", [_shot("B", "C")]), _survey("S2", [_shot("A", "B")])],
        fixed=fixed,
    )
    d = map_project(prj, report=ConversionReport("s", "o"))
    shots = _all_shots(d)
    starts = [s for s in shots if s["shot_type"] == "START"]
    assert [s["name"] for s in starts] == ["A"]          # only the fixed anchor
    assert "latitude" in starts[0]
    by_name = {s["name"]: s for s in shots}
    assert by_name["C"]["id_start"] == by_name["B"]["id_stop"]
    assert by_name["B"]["id_start"] == by_name["A"]["id_stop"]
    # sections keep their own shots
    sec_names = {sec["name"]: [s["name"] for s in sec["shots"]] for sec in d["sections"]}
    assert sec_names["S1"] == ["C"]
    assert sec_names["S2"] == ["A", "B"]


def test_tail_tie_chain_is_reversed():
    # Side passage surveyed toward the tie-in: S1 -> S2 -> A, A fixed.
    fixed = [FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")]
    prj = _project_multi(
        [_survey("S", [_shot("S1", "S2", bearing=10.0, inc=5.0),
                       _shot("S2", "A", bearing=20.0, inc=-3.0)])],
        fixed=fixed,
    )
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    shots = _all_shots(d)
    by_name = {s["name"]: s for s in shots}
    # chain reversed: A(START) -> S2 -> S1
    assert by_name["S2"]["id_start"] == by_name["A"]["id_stop"]
    assert by_name["S1"]["id_start"] == by_name["S2"]["id_stop"]
    assert by_name["S2"]["azimuth"] == pytest.approx(200.0)   # 20 + 180
    assert by_name["S2"]["inclination"] == pytest.approx(3.0)  # negated
    # reversal is report-only: no comment clutter in Ariane's data table
    assert not (by_name["S2"]["comment"] or "")
    assert any(e.category == "shot-reversed" for e in r.non_native())
    # no spurious START besides the anchor
    assert [s["name"] for s in shots if s["shot_type"] == "START"] == ["A"]


def test_isolated_component_anchored_at_base_location():
    # No fixed stations; project base location in Florida (UTM 17N meters).
    prj = _project_multi(
        [_survey("S", [_shot("X1", "X2")])],
        base=(284551.1, 3373992.3, 17),
    )
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    start = _all_shots(d)[0]
    assert start["shot_type"] == "START"
    assert start["latitude"] == pytest.approx(30.48, abs=0.05)
    assert start["longitude"] == pytest.approx(-83.24, abs=0.05)
    assert any(e.category == "component-unfixed" for e in r.entries)


def test_no_base_location_means_no_fake_coordinates():
    prj = _project_multi([_survey("S", [_shot("X1", "X2")])])
    d = map_project(prj, report=ConversionReport("s", "o"))
    start = _all_shots(d)[0]
    assert "latitude" not in start


def test_fixed_station_depth_is_in_feet():
    # Fixed station 100 ft below the first anchor must yield depth 100 (ft, not m).
    fixed = [
        FixedStation("A", "f", 933560.866, 11070112.205, 100.0, raw=""),
        FixedStation("B", "f", 933660.866, 11070112.205, 0.0, raw=""),
    ]
    prj = _project_multi(
        [_survey("S", [_shot("A", "A1")]), _survey("T", [_shot("B", "B1")])],
        fixed=fixed,
    )
    d = map_project(prj, report=ConversionReport("s", "o"))
    starts = {s["name"]: s for s in _all_shots(d) if s["shot_type"] == "START"}
    assert starts["A"]["depth"] == 0.0
    assert starts["B"]["depth"] == pytest.approx(100.0)  # 100 ft lower than A
