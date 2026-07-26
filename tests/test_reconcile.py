"""Data-integrity tests: the reconciliation auditor must (a) pass every clean
conversion and (b) actually DETECT corruption — proven here by deliberately
tampering with written files. The survey data cost thousands of dive hours;
these tests are the guarantee that none of it is silently lost or altered."""
import re
import zipfile
from pathlib import Path

from speleoconvert.ariane_writer import write_tml
from speleoconvert.compass.model import FixedStation, ShotFlags
from speleoconvert.mapping import map_project
from speleoconvert.reconcile import reconcile
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot


def _kitchen_sink_project():
    fixed = [FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw="")]
    shots = [
        _shot("E", "S1", length=100.0, bearing=90.0, inc=-30.0, left_ft=None,
              comment="silty & tight"),
        _shot("S1", "S2", flags=ShotFlags(exclude_all=True, raw="X")),
        _shot("S2", "S3", azm2_deg=272.5, inc2_deg=0.0),
        _shot("S3", "S4", flags=ShotFlags(exclude_plot=True, raw="P")),
        _shot("S4", "E", bearing=360.0),   # loop, with edge-case azimuth
    ]
    return _project(shots, fixed=fixed)


def _convert(prj, tmp_path: Path) -> Path:
    d = map_project(prj, report=ConversionReport("s", "o"))
    out = tmp_path / "out.tml"
    write_tml(d, out)
    return out


def _tamper(path: Path, pattern: str, replacement: str, count: int = 1) -> None:
    """count=0 means replace all occurrences (at least one)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("Data.xml").decode()
    new_xml, n = re.subn(pattern, replacement, xml, count=count)
    assert n >= 1 and (count == 0 or n == count), \
        f"tamper pattern {pattern!r}: {n} replacements"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("Data.xml", new_xml)


def test_clean_conversion_reconciles(tmp_path):
    prj = _kitchen_sink_project()
    assert reconcile(prj, _convert(prj, tmp_path)) == []


def test_detects_altered_length(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Length>100</Length>", "<Length>101</Length>")
    assert reconcile(prj, out)


def test_detects_dropped_shot(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    with zipfile.ZipFile(out) as z:
        xml = z.read("Data.xml").decode()
    # remove one whole SurveyData element (a REAL shot)
    parts = xml.split("<SurveyData>")
    assert len(parts) > 3
    xml = "<SurveyData>".join(parts[:2] + parts[3:])
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("Data.xml", xml)
    problems = reconcile(prj, out)
    assert any("MISSING" in p or "shot count" in p for p in problems)


def test_detects_altered_azimuth(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Azimut>90\.0</Azimut>", "<Azimut>91.0</Azimut>")
    assert any("azimuth" in p for p in reconcile(prj, out))


def test_detects_lost_comment(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Comment>[^<]*silty[^<]*</Comment>", "<Comment/>")
    assert any("comment" in p and "lost" in p for p in reconcile(prj, out))


def test_detects_flipped_excluded(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Excluded>true</Excluded>", "<Excluded>false</Excluded>")
    assert any("Excluded" in p for p in reconcile(prj, out))


def test_detects_altered_lrud(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Up>1</Up>", "<Up>2</Up>")
    assert any("up" in p for p in reconcile(prj, out))


def test_detects_lost_team_member(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    _tamper(out, r"<Explorer>Matt</Explorer>", "<Explorer></Explorer>",
            count=0)
    assert any("team member" in p for p in reconcile(prj, out))


def test_detects_corrupted_depth_chain(tmp_path):
    prj = _kitchen_sink_project()
    out = _convert(prj, tmp_path)
    # S1 sits 50 ft down (100 ft at -30 deg); zero it out
    _tamper(out, r"<Depth>50</Depth>", "<Depth>0</Depth>")
    assert any("depth delta" in p for p in reconcile(prj, out))
