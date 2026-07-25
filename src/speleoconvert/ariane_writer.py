"""The ONLY module allowed to import openspeleo_lib (see spec: firewall)."""
from __future__ import annotations

from pathlib import Path

from openspeleo_lib.generators import UniqueValueGenerator
from openspeleo_lib.interfaces.ariane.interface import ArianeInterface, ArianeSurvey


def write_tml(survey_dict: dict, out_path: Path) -> None:
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, Path(out_path))


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
