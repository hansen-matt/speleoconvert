import zipfile
from pathlib import Path

from speleoconvert.ariane_writer import read_tml, write_tml


def _minimal_survey() -> dict:
    return {
        "name": "spike",
        "unit": "FT",
        "first_start_absolute_elevation": 10.0,
        "use_magnetic_azimuth": True,
        "sections": [
            {
                "name": "S1",
                "survey": None,
                "date": "2024-02-23",
                "explorers": [],
                "surveyors": ["Matt Hansen"],
                "declination": -6.13,
                "compass_format": "DDDWLRUDLAaDdNF",
                "correction": [0.0, 0.0, 0.0],
                "correction2": [0.0, 0.0],
                "shots": [
                    {
                        "id_stop": 0, "section": None, "shot_type": "START",
                        "name": "ENTRANCE", "length": 0.0, "depth": 0.0,
                        "azimuth": 0.0, "latitude": 30.1, "longitude": -83.2,
                    },
                    {
                        "id_start": 0, "id_stop": 1, "section": None, "name": "L1",
                        "length": 110.0, "depth": 3.0, "depth_start": 0.0,
                        "azimuth": 338.0, "inclination": 1.56,
                        "right": 8.0, "up": 3.0, "down": 3.0, "left": None,
                        "comment": "hello",
                    },
                ],
            }
        ],
    }


def test_write_and_reread(tmp_path: Path):
    out = tmp_path / "out.tml"
    write_tml(_minimal_survey(), out)
    with zipfile.ZipFile(out) as z:
        assert "Data.xml" in z.namelist()
        xml = z.read("Data.xml").decode()
    assert "<caveName>spike</caveName>" in xml
    assert "<unit>ft</unit>" in xml
    back = read_tml(out)
    shot = back.sections[0].shots[1]
    assert shot.name == "L1"
    assert shot.left is None          # absent LRUD round-trips as absent
    assert shot.length == 110.0
    # after Explorer flattening (plain text for Ariane's table), the re-read
    # library puts the names in explorers rather than surveyors
    team = (back.sections[0].surveyors or []) + (back.sections[0].explorers or [])
    assert "Matt Hansen" in " ".join(team)
