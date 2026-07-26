"""Conversion audit report: every non-native mapping decision, machine+human readable."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass

from speleoconvert import __version__

NATIVE = "native"
COMMENT = "comment"
REPORT_ONLY = "report-only"
ERROR = "error"

STRICT_EXEMPT_CATEGORIES = {
    "mak-display-flags",
    "mak-unknown-param",
    "mak-comment",
    "mak-convergence",
    "format-display-order",
    "lrud-missing",
    # link stations are plain references to stations that exist in the shot
    # data; nothing is lost by not re-declaring them.
    "mak-link-station",
    # a survey component with no fixed station has no defined absolute position
    # in Compass either; we anchor it at the base location and note it.
    "component-unfixed",
    # chain reversal is REQUIRED by Ariane's rooted-tree model whenever a chain
    # was surveyed toward its tie-in; it is geometry-preserving (azimuth +180,
    # inclination negated, left/right walls swapped) and every reversal is
    # itemized in the report.
    "shot-reversed",
    # the Compass editor's all-zero "From Station  To Station" template row is
    # not survey data; skipping it loses nothing.
    "placeholder-shot",
    # backsight averaging is what Compass itself does at compile time; the raw
    # readings are preserved in the shot comment and the report.
    "backsight-averaged",
    "backsight-discrepancy",
    "bearing-from-backsight",
    # TML cannot store declination (Ariane derives it from date+location);
    # the recorded value is embedded in every section comment. Flagging it in
    # strict mode would reject every survey ever made.
    "survey-declination",
    "declination-zero",
    # the FORMAT string is data-entry display metadata; values are already
    # normalized to feet/degrees on disk.
    "survey-format",
    # Ariane's rooted-tree model anchors one station per connected component;
    # secondary GPS anchors are preserved verbatim in the shot comment.
    "fixed-station-secondary",
    # cave name != survey name is the normal Compass file structure; the name is
    # still preserved in the section comment, so strict mode must not reject it.
    "survey-cave-name",
}


@dataclass(frozen=True)
class ReportEntry:
    category: str
    disposition: str
    location: str
    message: str


class StrictModeError(Exception):
    def __init__(self, entries: list[ReportEntry]) -> None:
        self.entries = entries
        lines = "\n".join(f"  {e.location}: [{e.category}] {e.message}" for e in entries)
        super().__init__(
            f"{len(entries)} field(s) have no native Ariane equivalent "
            f"(rerun without --strict to embed them in comments):\n{lines}"
        )


class ConversionReport:
    def __init__(self, source: str, output: str) -> None:
        self.source, self.output = source, output
        self.entries: list[ReportEntry] = []

    def add(self, category: str, disposition: str, location: str, message: str) -> None:
        self.entries.append(ReportEntry(category, disposition, location, message))

    def non_native(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.disposition != NATIVE]

    def strict_violations(self) -> list[ReportEntry]:
        return [
            e for e in self.non_native() if e.category not in STRICT_EXEMPT_CATEGORIES
        ]

    def counts(self) -> dict[str, int]:
        return dict(Counter(e.category for e in self.entries))

    def to_json(self) -> str:
        return json.dumps(
            {
                "tool": f"speleoconvert {__version__}",
                "source": self.source,
                "output": self.output,
                "counts": self.counts(),
                "entries": [asdict(e) for e in self.entries],
            },
            indent=2,
        )

    def summary_text(self) -> str:
        lines = [f"speleoconvert report: {self.source} -> {self.output}"]
        for cat, n in sorted(self.counts().items()):
            lines.append(f"  {cat}: {n}")
        nn = self.non_native()
        if nn:
            lines.append("non-native mappings:")
            lines.extend(f"  {e.location}: [{e.category}] {e.message}" for e in nn)
        else:
            lines.append("all data mapped natively.")
        return "\n".join(lines)
