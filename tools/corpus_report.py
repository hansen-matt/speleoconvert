"""Survey the corpus: strict-mode readiness of every project.

Usage: SPELEOCONVERT_CORPUS=... uv run python tools/corpus_report.py
"""
import os
import sys
from pathlib import Path

from speleoconvert.compass.parser_mak import load_project
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport, StrictModeError

corpus = os.environ.get("SPELEOCONVERT_CORPUS")
if not corpus:
    sys.exit("set SPELEOCONVERT_CORPUS")

maks = sorted(p for p in Path(corpus).rglob("*") if p.suffix.lower() == ".mak")
for i, mak in enumerate(maks, 1):
    label = f"[{i}/{len(maks)}] {mak.parent.name}/{mak.name}"
    try:
        project = load_project(mak)
        n_shots = sum(len(s.shots) for d in project.dat_files for s in d.surveys)
        report = ConversionReport(str(mak), "-")
        try:
            map_project(project, strict=True, report=report)
            status = "STRICT-OK"
        except StrictModeError as e:
            cats = sorted({en.category for en in e.entries})
            status = f"strict-violations: {','.join(cats)}"
        print(f"{label}: {n_shots} shots, {status}")
    except Exception as e:  # noqa: BLE001 - survey tool, keep going
        print(f"{label}: FAILED - {e}")
