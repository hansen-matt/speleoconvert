"""Randomized end-to-end integrity: generate synthetic Compass projects
(genuine .DAT/.MAK bytes with loops, branches, shuffled shot order forcing
reversals, backsight columns, sentinels, flags, ampersands, edge-case
bearings), run the full pipeline, and require PERFECT shot-by-shot
reconciliation of the written TML against the parsed source."""
import random
from pathlib import Path

import pytest

from speleoconvert.ariane_writer import write_tml
from speleoconvert.compass.parser_mak import load_project
from speleoconvert.conformance import validate_tml
from speleoconvert.mapping import map_project
from speleoconvert.reconcile import reconcile
from speleoconvert.report import ConversionReport

HEADER = ("                FROM                   TO   LENGTH  BEARING      INC"
          "     LEFT       UP     DOWN    RIGHT{bs}   FLAGS  COMMENTS")


def _fmt(v):
    return f"{v:9.2f}"


def _gen_survey(rng: random.Random, idx: int, stations: list[str]) -> str:
    has_backsights = rng.random() < 0.4
    n_shots = rng.randint(3, 12)
    start = rng.choice(stations) if stations and rng.random() < 0.7 else f"S{idx}_0"
    local = [start]
    lines = []
    for j in range(n_shots):
        frm = rng.choice(local)
        if stations and rng.random() < 0.08:
            to = rng.choice(stations)      # loop / tie into earlier survey
            if to == frm:
                to = f"S{idx}_{j+1}"
        else:
            to = f"S{idx}_{j+1}"
        local.append(to)
        length = round(rng.uniform(0.5, 250.0), 2)
        bearing = rng.choice([0.0, 360.0, round(rng.uniform(0, 359.99), 2),
                              round(rng.uniform(0, 359.99), 2)])
        inc = round(rng.uniform(-85, 85), 2)
        lrud = [(-9.90 if rng.random() < 0.3 else round(rng.uniform(0, 80), 2))
                for _ in range(4)]
        row = (f"{frm:>20s} {to:>20s} {_fmt(length)} {_fmt(bearing)} {_fmt(inc)}"
               f" {_fmt(lrud[0])} {_fmt(lrud[1])} {_fmt(lrud[2])} {_fmt(lrud[3])}")
        if has_backsights:
            if rng.random() < 0.8:
                azm2 = round((bearing + 180 + rng.uniform(-1.5, 1.5)) % 360, 2)
                inc2 = round(-inc + rng.uniform(-1.0, 1.0), 2)
            else:
                azm2 = inc2 = -999.25
            row += f" {_fmt(azm2)} {_fmt(inc2)}"
        r = rng.random()
        if r < 0.10:
            row += "  #|X#"
        elif r < 0.18:
            row += "  #|PC#  low viz & flow"
        elif r < 0.30:
            row += "        promising lead <check wall>"
        lines.append(row)
    stations.extend(s for s in local if s not in stations)

    # shots in shuffled order: forces deferred emission and chain reversal
    rng.shuffle(lines)
    team = rng.choice(["A. Diver,B. Diver", "Pitkin & Roberson,C. Mapper", "?"])
    bs_hdr = "     AZM2     INC2" if has_backsights else ""
    return (
        f"Fuzz Cave & Spring\r\n"
        f"SURVEY NAME: FZ{idx}\r\n"
        f"SURVEY DATE: {rng.randint(1,12)} {rng.randint(1,28)} "
        f"{rng.randint(1985, 2025)}  COMMENT:gen {idx}\r\n"
        "SURVEY TEAM: \r\n"
        f"{team}\r\n"
        f"DECLINATION: {rng.uniform(-8, 8):7.2f}  FORMAT: DDDWLRUDLAaDdNF  "
        "CORRECTIONS:  0.00 0.00 0.00  CORRECTIONS2:  0.00 0.00\r\n"
        "\r\n" + HEADER.format(bs=bs_hdr) + "\r\n\r\n"
        + "\r\n".join(lines) + "\r\n"
    )


def _gen_project(rng: random.Random, tmp_path: Path) -> Path:
    stations: list[str] = []
    surveys = [_gen_survey(rng, i, stations) for i in range(rng.randint(2, 6))]
    (tmp_path / "fuzz.dat").write_bytes("\x0c".join(surveys).encode("cp437"))
    anchor = stations[0]
    mak = (
        "@284551.100,3373992.300,0.000,17,-1.140;\r\n&WGS 1984;\r\n$17;\r\n"
        f"#fuzz.dat,\r\n {anchor}[f,933560.866,11070112.205,0.000];\r\n"
    )
    (tmp_path / "fuzz.mak").write_bytes(mak.encode("cp437"))
    return tmp_path / "fuzz.mak"


@pytest.mark.parametrize("seed", range(12))
def test_random_project_survives_pipeline_intact(seed, tmp_path):
    rng = random.Random(seed)
    mak = _gen_project(rng, tmp_path)
    project = load_project(mak)
    d = map_project(project, report=ConversionReport("s", "o"))
    out = tmp_path / "fuzz.tml"
    write_tml(d, out)

    assert validate_tml(out) == []            # format conformance
    assert reconcile(project, out) == []      # zero data loss or corruption
