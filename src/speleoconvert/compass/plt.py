"""Minimal Compass .plt reader — verification only (station positions)."""
from __future__ import annotations

from pathlib import Path


def parse_plt(path: str | Path) -> dict[str, tuple[float, float, float]]:
    stations: dict[str, tuple[float, float, float]] = {}
    text = Path(path).read_bytes().decode("cp437", errors="replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] in ("M", "D"):
            try:
                north, east, vert = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            for tok in parts[4:]:
                if tok.startswith("S") and len(tok) > 1:
                    stations.setdefault(tok[1:], (north, east, vert))
                    break
    return stations
