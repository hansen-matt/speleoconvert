"""The ONLY module allowed to import openspeleo_lib (see spec: firewall)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from openspeleo_lib.generators import UniqueValueGenerator
from openspeleo_lib.interfaces.ariane.interface import ArianeInterface, ArianeSurvey

# Ariane's native Explorer encoding (verified against hand_survey.tml, a real
# Ariane-authored cave file) is an escaped embedded fragment with BOTH tags:
#     <Explorer>&lt;Explorer&gt;E&lt;/Explorer&gt;&lt;Surveyor&gt;S&lt;/Surveyor&gt;</Explorer>
# The library instead writes a Surveyor-only fragment when explorers are empty,
# which Ariane fails to parse and renders raw. Rewrite to the native form,
# using the Compass survey team as both explorers and surveyors.
_EXPLORER_RE = re.compile(r"<Explorer>&lt;Surveyor&gt;(.*?)&lt;/Surveyor&gt;</Explorer>")

# The library also writes XMLExplorer/XMLSurveyor tags on every shot. Real
# Ariane files don't contain them, and Ariane renders them into the Explorer
# column as literal text. Drop them.
_XML_TEAM_TAGS_RE = re.compile(
    r"<XMLExplorer>.*?</XMLExplorer>|<XMLExplorer/>"
    r"|<XMLSurveyor>.*?</XMLSurveyor>|<XMLSurveyor/>"
)


def _native_explorer(match: re.Match) -> str:
    team = match.group(1)
    return (
        "<Explorer>"
        f"&lt;Explorer&gt;{team}&lt;/Explorer&gt;"
        f"&lt;Surveyor&gt;{team}&lt;/Surveyor&gt;"
        "</Explorer>"
    )


def write_tml(survey_dict: dict, out_path: Path) -> None:
    out_path = Path(out_path)
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("Data.xml").decode()
    fixed = _EXPLORER_RE.sub(_native_explorer, xml)
    fixed = _XML_TEAM_TAGS_RE.sub("", fixed)
    if fixed != xml:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("Data.xml", fixed)


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
