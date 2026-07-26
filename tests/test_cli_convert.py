import json
from pathlib import Path

from speleoconvert.cli import main

MAK = (
    "@284551.100,3373992.300,0.000,17,-1.140;\r\n&WGS 1984;\r\n$17;\r\n"
    "#mini.dat,\r\n E[f,933560.866,11070112.205,0.000];\r\n"
)
DAT = (
    "cave\r\nSURVEY NAME: A\r\nSURVEY DATE: 2 23 2024  COMMENT:\r\n"
    "SURVEY TEAM: \r\nMatt\r\n"
    "DECLINATION: -6.13  FORMAT: DDDWLRUDLAaDdNF  CORRECTIONS: 0.00 0.00 0.00"
    "  CORRECTIONS2: 0.00 0.00\r\n"
    "\r\nFROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
    "E S1 100.00 90.00 -30.00 1.00 2.00 3.00 4.00\r\n"
    "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00\r\n"
)


def _mini(tmp_path: Path) -> Path:
    (tmp_path / "mini.mak").write_bytes(MAK.encode("cp437"))
    (tmp_path / "mini.dat").write_bytes(DAT.encode("cp437"))
    return tmp_path / "mini.mak"


def test_convert_end_to_end(tmp_path, capsys):
    mak = _mini(tmp_path)
    assert main(["convert", str(mak)]) == 0
    out = tmp_path / "mini.tml"
    assert out.exists()
    rep = json.loads((tmp_path / "mini.tml.report.json").read_text())
    assert rep["source"].endswith("mini.mak")
    # verify TML round-trips through openspeleo
    from speleoconvert.ariane_writer import read_tml
    back = read_tml(out)
    assert back.name == "mini"
    names = [s.name for s in back.sections[0].shots]
    assert names == ["E", "S1", "S2"]
    assert "speleoconvert report" in capsys.readouterr().out


def test_convert_strict_passes_clean_project(tmp_path):
    mak = _mini(tmp_path)
    assert main(["convert", str(mak), "--strict"]) == 0


def test_convert_strict_fails_flagged_project(tmp_path, capsys):
    (tmp_path / "mini.mak").write_bytes(MAK.encode("cp437"))
    flagged = DAT.replace(
        "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00",
        "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00  #|P#  low vis",
    )
    (tmp_path / "mini.dat").write_bytes(flagged.encode("cp437"))
    assert main(["convert", str(tmp_path / "mini.mak"), "--strict"]) == 1
    assert "no native Ariane equivalent" in capsys.readouterr().err


def test_convert_missing_file_exit_1(tmp_path, capsys):
    assert main(["convert", str(tmp_path / "nope.mak")]) == 1
