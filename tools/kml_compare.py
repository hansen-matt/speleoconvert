"""Compare two cave-survey KML exports (e.g. Ariane vs Compass) geometrically.

Usage: uv run python tools/kml_compare.py ARIANE.kml COMPASS.kml

Extracts every coordinate from both files and reports the nearest-neighbor
distance distribution in both directions (ft), plus the centroid offset.
Interpreting results: sub-10-ft p95 = the engines agree; a uniform offset =
datum/anchor difference; distance growing with range from the entrance =
declination difference (rotation); localized blowups = loop-compensation
differences on specific loops.
"""
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

FT_PER_DEG_LAT = 364000.0


def load_points(path: Path) -> list[tuple[float, float]]:
    text = path.read_text(errors="replace")
    pts: list[tuple[float, float]] = []
    for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, re.S):
        for triple in block.split():
            parts = triple.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                pts.append((lat, lon))
    return pts


def to_ft(pts, lat0):
    k = math.cos(math.radians(lat0))
    return [(lat * FT_PER_DEG_LAT, lon * FT_PER_DEG_LAT * k) for lat, lon in pts]


def nn_distances(a, b, cell=50.0):
    """Nearest-neighbor distance from each point of a to the set b (ft)."""
    grid = defaultdict(list)
    for p in b:
        grid[(int(p[0] // cell), int(p[1] // cell))].append(p)
    out = []
    for x, y in a:
        cx, cy = int(x // cell), int(y // cell)
        best = float("inf")
        r = 1
        while True:
            for i in range(cx - r, cx + r + 1):
                for j in range(cy - r, cy + r + 1):
                    for q in grid.get((i, j), ()):
                        d = math.hypot(x - q[0], y - q[1])
                        if d < best:
                            best = d
            if best <= (r - 0.5) * cell or r > 200:
                break
            r += 1
        out.append(best)
    return out


def stats(ds):
    ds = sorted(ds)
    n = len(ds)
    return (f"median {ds[n // 2]:7.1f}  p95 {ds[int(0.95 * (n - 1))]:7.1f}  "
            f"max {ds[-1]:7.1f}  (n={n})")


def main():
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    a_raw, b_raw = load_points(a_path), load_points(b_path)
    if not a_raw or not b_raw:
        sys.exit(f"no coordinates found ({len(a_raw)} vs {len(b_raw)})")
    lat0 = a_raw[0][0]
    a, b = to_ft(a_raw, lat0), to_ft(b_raw, lat0)
    ca = (sum(p[0] for p in a) / len(a), sum(p[1] for p in a) / len(a))
    cb = (sum(p[0] for p in b) / len(b), sum(p[1] for p in b) / len(b))
    print(f"A: {a_path.name}  ({len(a)} points)")
    print(f"B: {b_path.name}  ({len(b)} points)")
    print(f"centroid offset: {math.hypot(ca[0]-cb[0], ca[1]-cb[1]):.1f} ft "
          f"(dN {ca[0]-cb[0]:+.1f}, dE {ca[1]-cb[1]:+.1f})")
    print(f"A -> B nearest-neighbor ft: {stats(nn_distances(a, b))}")
    print(f"B -> A nearest-neighbor ft: {stats(nn_distances(b, a))}")


if __name__ == "__main__":
    main()
