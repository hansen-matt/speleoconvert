from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from speleoconvert import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="speleoconvert",
        description="Lossless Fountainware Compass -> Ariane's Line converter",
    )
    parser.add_argument("--version", action="version", version=f"speleoconvert {__version__}")
    sub = parser.add_subparsers(dest="command")
    conv = sub.add_parser("convert", help="convert a Compass project (.mak) to .tml")
    conv.add_argument("mak", type=Path, help="Compass project file (.mak)")
    conv.add_argument("-o", "--output", type=Path, default=None, help=".tml output path")
    conv.add_argument("--strict", action="store_true",
                      help="error on any field without a native Ariane equivalent")
    conv.add_argument("--report", type=Path, default=None,
                      help="report path (default: <output>.report.json)")
    conv.add_argument("-q", "--quiet", action="store_true", help="suppress summary")

    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.command != "convert":
        parser.print_usage(sys.stderr)
        return 2
    return _convert(args)


def _convert(args: argparse.Namespace) -> int:
    # imports deferred so `--version`/usage never require heavy deps
    from speleoconvert.ariane_writer import write_tml
    from speleoconvert.compass.model import ParseError
    from speleoconvert.compass.parser_mak import load_project
    from speleoconvert.geodesy import GeodesyError
    from speleoconvert.mapping import map_project
    from speleoconvert.reconcile import reconcile
    from speleoconvert.report import ConversionReport, StrictModeError

    out = args.output or args.mak.with_suffix(".tml")
    if out.suffix.lower() != ".tml":
        print(f"error: output must be a .tml file, got {out}", file=sys.stderr)
        return 2
    report_path = args.report or Path(f"{out}.report.json")
    paths = {p.resolve() for p in (args.mak, out, report_path)}
    if len(paths) != 3:
        print("error: input, output, and report paths must all differ "
              f"({args.mak} / {out} / {report_path})", file=sys.stderr)
        return 2
    report = ConversionReport(source=str(args.mak), output=str(out))
    try:
        project = load_project(args.mak)
        survey_dict = map_project(project, strict=args.strict, report=report)
        write_tml(survey_dict, out)
    except (ParseError, GeodesyError, StrictModeError, FileNotFoundError,
            OSError, ValueError, TypeError) as e:
        # ValueError also covers pydantic ValidationError from the writer
        print(f"error: {e}", file=sys.stderr)
        if report.entries:  # keep whatever audit trail exists
            with contextlib.suppress(OSError):
                report_path.write_text(report.to_json())
        return 1

    # Every conversion self-audits: the written file is independently re-read
    # and reconciled shot-by-shot against the Compass source, then validated
    # against the de-facto Ariane format. The report is written regardless,
    # so failed runs keep their audit trail.
    from speleoconvert.conformance import validate_tml

    problems = reconcile(project, out)
    problems += [f"format conformance: {p}" for p in validate_tml(out)]
    if problems:
        for p in problems[:20]:
            print(f"VERIFICATION FAILURE: {p}", file=sys.stderr)
        if len(problems) > 20:
            print(f"... and {len(problems) - 20} more", file=sys.stderr)
        report_path.write_text(report.to_json())
        print(f"error: output failed verification against the source; "
              f"{out} must not be trusted (audit trail in {report_path})",
              file=sys.stderr)
        return 1

    report_path.write_text(report.to_json())
    if not args.quiet:
        print(report.summary_text())
        n = sum(len(s.shots) for d in project.dat_files for s in d.surveys)
        print(f"reconciliation: OK ({n} shots verified against the source)")
        print(f"wrote {out}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
