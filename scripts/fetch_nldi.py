"""Snapshot map layers for each gauge from the USGS Network-Linked Data Index (NLDI).

Writes data/snapshot/nldi/<site>.json with three GeoJSON layers:
  basin      the gauge's upstream drainage basin (polygon)
  upstream   the upstream main stem flowlines (UM, up to UPSTREAM_KM)
  downstream the downstream main stem flowlines (DM, up to DOWNSTREAM_KM)

Coordinates are rounded to 4 decimals (about 10 m), which keeps the files small; the map is a
locator, not survey data. Run once with network access; the console then draws these offline.

    python scripts/fetch_nldi.py            # all 8 sites
    python scripts/fetch_nldi.py 03455000   # one site
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from driftwatch.modules.rating_curve.usgs import SITES

NLDI = "https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{site}"
UPSTREAM_KM = 150
DOWNSTREAM_KM = 40
OUT = Path(__file__).resolve().parents[1] / "data" / "snapshot" / "nldi"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "driftwatch-snapshot"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _round(coords):
    if coords and isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def _slim(fc: dict) -> dict:
    """Keep geometry only (rounded); drop per-feature properties the map doesn't use."""
    feats = []
    for f in fc.get("features", []):
        g = f.get("geometry")
        if g:
            feats.append({"type": "Feature", "properties": {},
                          "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}})
    return {"type": "FeatureCollection", "features": feats}


def fetch(site: str) -> Path:
    base = NLDI.format(site=site)
    layers = {
        "basin": _slim(_get(f"{base}/basin?f=json")),
        "upstream": _slim(_get(f"{base}/navigation/UM/flowlines?distance={UPSTREAM_KM}&f=json")),
        "downstream": _slim(_get(f"{base}/navigation/DM/flowlines?distance={DOWNSTREAM_KM}&f=json")),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{site}.json"
    doc = {"site": site, "source": base, "upstream_km": UPSTREAM_KM, "downstream_km": DOWNSTREAM_KM, **layers}
    path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n = {k: len(v["features"]) for k, v in layers.items()}
    print(f"{site}: basin {n['basin']}, upstream {n['upstream']}, downstream {n['downstream']} features "
          f"-> {path.name} ({path.stat().st_size // 1024} KB)")
    return path


if __name__ == "__main__":
    for s in sys.argv[1:] or SITES:
        fetch(s)
