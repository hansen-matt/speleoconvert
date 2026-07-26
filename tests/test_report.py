import json

from speleoconvert.report import (
    COMMENT,
    NATIVE,
    REPORT_ONLY,
    ConversionReport,
)


def test_report_collects_and_serializes():
    r = ConversionReport(source="a.mak", output="a.tml")
    r.add("backsight", COMMENT, "a.dat:12", "AZM2=158.0 INC2=-1.5 appended to comment")
    r.add("lrud-missing", REPORT_ONLY, "a.dat:10", "LEFT absent")
    r.add("shot", NATIVE, "a.dat:10", "ok")
    assert len(r.non_native()) == 2
    data = json.loads(r.to_json())
    assert data["source"] == "a.mak"
    assert data["counts"]["backsight"] == 1
    assert len(data["entries"]) == 3
    txt = r.summary_text()
    assert "backsight" in txt and "a.dat:12" in txt


def test_strict_violations_respect_exemptions():
    r = ConversionReport(source="a.mak", output="a.tml")
    r.add("lrud-missing", REPORT_ONLY, "a.dat:10", "LEFT absent")     # exempt
    r.add("mak-display-flags", REPORT_ONLY, "a.mak", "!gEv;")         # exempt
    r.add("backsight", COMMENT, "a.dat:12", "azm2")                   # NOT exempt
    assert [e.category for e in r.strict_violations()] == ["backsight"]
