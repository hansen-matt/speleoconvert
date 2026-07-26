"""The ONLY module allowed to import openspeleo_lib (see spec: firewall)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from openspeleo_lib.generators import UniqueValueGenerator
from openspeleo_lib.interfaces.ariane.interface import ArianeInterface, ArianeSurvey

# Ariane's data table displays the Explorer field as RAW text — verified with
# a screenshot of an Ariane-authored file (embedded <Explorer>/<Surveyor>
# fragments render as literal tags on screen). The only form that displays
# cleanly is plain text, which is itself genuine Ariane output (test_simple.tml
# in the OpenSpeleo test artifacts stores a bare string). Rewrite the library's
# embedded fragment — Surveyor-only or both-tags — to plain comma-joined names.
_EXPLORER_RE = re.compile(
    r"<Explorer>"
    r"(?:&lt;Explorer&gt;(?P<expl>.*?)&lt;/Explorer&gt;)?"
    r"(?:&lt;Surveyor&gt;(?P<surv>.*?)&lt;/Surveyor&gt;)?"
    r"</Explorer>"
)

# Inner-fragment text is escaped twice (fragment serializer + XML writer);
# plain text must be escaped exactly once. Collapse one level for recognized
# entities only.
_DOUBLE_ESCAPE_RE = re.compile(r"&amp;(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")

# The library also writes XMLExplorer/XMLSurveyor tags on every shot. Real
# Ariane files don't contain them and Ariane renders them as literal text.
_XML_TEAM_TAGS_RE = re.compile(
    r"<XMLExplorer>.*?</XMLExplorer>|<XMLExplorer/>"
    r"|<XMLSurveyor>.*?</XMLSurveyor>|<XMLSurveyor/>"
)

# The library writes CSS-style colors (#FFB366); every Ariane-authored file
# uses 0xrrggbbaa (opaque alpha 'ff' on normal shots).
_CSS_COLOR_RE = re.compile(r"<Color>#([0-9a-fA-F]{6})</Color>")


def _plain_explorer(match: re.Match) -> str:
    parts = [p for p in (match.group("expl"), match.group("surv")) if p]
    # explorers and surveyors are usually the same team; don't repeat names
    names = ",".join(dict.fromkeys(n for part in parts for n in part.split(",")))
    names = _DOUBLE_ESCAPE_RE.sub(r"&\1;", names)
    return f"<Explorer>{names}</Explorer>"


def write_tml(survey_dict: dict, out_path: Path) -> None:
    out_path = Path(out_path)
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("Data.xml").decode()
    fixed = _EXPLORER_RE.sub(_plain_explorer, xml)
    fixed = _XML_TEAM_TAGS_RE.sub("", fixed)
    fixed = _CSS_COLOR_RE.sub(lambda m: f"<Color>0x{m.group(1).lower()}ff</Color>",
                              fixed)
    if fixed != xml:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("Data.xml", fixed)


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
