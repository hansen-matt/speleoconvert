from __future__ import annotations

import sys

from speleoconvert import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print(f"speleoconvert {__version__}")
        return 0
    print("usage: speleoconvert convert <project.mak> [options]", file=sys.stderr)
    return 2


def entrypoint() -> None:
    raise SystemExit(main())
