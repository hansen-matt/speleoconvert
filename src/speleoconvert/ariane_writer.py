"""The ONLY module allowed to import openspeleo_lib (see spec: firewall)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from openspeleo_lib.generators import UniqueValueGenerator
from openspeleo_lib.interfaces.ariane.interface import ArianeInterface, ArianeSurvey

# The library wraps surveyor names in escaped XML (<Surveyor>...</Surveyor>)
# inside the Explorer field, but Ariane's data table renders that field as
# PLAIN TEXT (verified against a real Ariane-authored file, where Explorer is
# a bare string). Flatten it after writing.
_EXPLORER_RE = re.compile(r"<Explorer>&lt;Surveyor&gt;(.*?)&lt;/Surveyor&gt;</Explorer>")

# Names inside the Explorer wrapper are escaped twice upstream (once by the
# embedded-fragment serializer, once by the XML writer), so "A & B" arrives as
# "A &amp;amp; B" and Ariane would display "A &amp; B". Collapse exactly one
# escaping level for recognized entities; everything else is left untouched.
_DOUBLE_ESCAPE_RE = re.compile(r"&amp;(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _flatten_explorer(match: re.Match) -> str:
    names = _DOUBLE_ESCAPE_RE.sub(r"&\1;", match.group(1))
    return f"<Explorer>{names}</Explorer>"


# The library also writes XMLExplorer/XMLSurveyor tags on every shot. Real
# Ariane files don't contain them, and (at least some) Ariane versions render
# them into the Explorer column as literal '<Explorer></Explorer><Surveyor>..'
# text. The plain Explorer field already carries the names — drop the tags.
_XML_TEAM_TAGS_RE = re.compile(
    r"<XMLExplorer>.*?</XMLExplorer>|<XMLExplorer/>"
    r"|<XMLSurveyor>.*?</XMLSurveyor>|<XMLSurveyor/>"
)


def write_tml(survey_dict: dict, out_path: Path) -> None:
    out_path = Path(out_path)
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("Data.xml").decode()
    flattened = _EXPLORER_RE.sub(_flatten_explorer, xml)
    flattened = _XML_TEAM_TAGS_RE.sub("", flattened)
    if flattened != xml:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("Data.xml", flattened)


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
