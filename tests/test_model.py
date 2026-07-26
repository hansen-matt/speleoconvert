import pytest

from speleoconvert.compass.model import FormatSpec, ParseError, ShotFlags


@pytest.mark.parametrize(
    "raw,az,length,lrud,inc,order,items,bs,assoc",
    [
        ("DDDWLRUDLAaDdNF", "D", "D", "D", "W", "LRUD", "LAaDd", "N", "F"),
        ("DDDWUDRLLADN", "D", "D", "D", "W", "UDRL", "LAD", "N", "F"),
        ("DMMDLRUDLADNT", "D", "M", "M", "D", "LRUD", "LAD", "N", "T"),
        ("DIDWUDRLLAaDdNF", "D", "I", "D", "W", "UDRL", "LAaDd", "N", "F"),
        ("DDDWLRUDLDAN", "D", "D", "D", "W", "LRUD", "LDA", "N", "F"),
        ("DDDDUDRLLADN", "D", "D", "D", "D", "UDRL", "LAD", "N", "F"),
    ],
)
def test_format_spec_corpus_variants(raw, az, length, lrud, inc, order, items, bs, assoc):
    f = FormatSpec.parse(raw, file="x.dat", line_no=6)
    assert (f.azimuth_unit, f.length_unit, f.lrud_unit, f.inclination_unit) == (
        az, length, lrud, inc,
    )
    assert f.lrud_order == order
    assert f.item_order == items
    assert f.backsight_flag == bs
    assert f.lrud_association == assoc
    assert f.raw == raw


@pytest.mark.parametrize("raw", ["DDDZLRUDLADN", "DDDWLXUDLADN", "DDDWLRUDQQQN", "SHORT"])
def test_format_spec_rejects_unknown(raw):
    with pytest.raises(ParseError) as e:
        FormatSpec.parse(raw, file="x.dat", line_no=6)
    assert "x.dat:6" in str(e.value)


def test_flags_parse():
    f = ShotFlags.parse("#|PC#")
    assert f.exclude_plot and f.no_adjust
    assert not f.exclude_length and not f.exclude_all
    assert f.raw == "PC"
