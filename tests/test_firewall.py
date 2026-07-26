import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "speleoconvert"


def test_only_ariane_writer_imports_openspeleo():
    offenders = [
        p for p in SRC.rglob("*.py")
        if "openspeleo" in p.read_text() and p.name != "ariane_writer.py"
    ]
    assert offenders == []


def test_compass_package_is_stdlib_only():
    code = (
        "import sys; mods_before=set(sys.modules); "
        "import speleoconvert.compass.model, speleoconvert.compass.parser_dat, "
        "speleoconvert.compass.parser_mak; "
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        "('openspeleo_lib','pyproj','pydantic','orjson')]; "
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
