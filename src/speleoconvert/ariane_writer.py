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


def write_tml(survey_dict: dict, out_path: Path) -> None:
    out_path = Path(out_path)
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("Data.xml").decode()
    flattened = _EXPLORER_RE.sub(r"<Explorer>\1</Explorer>", xml)
    if flattened != xml:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("Data.xml", flattened)


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
