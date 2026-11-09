"""Save USGS National Map hillshade + hydrography tiles for the console's gauge map, so it has a basemap offline.

Writes driftwatch/api/static/basemap/<layer>_<z>_<x>_<y>.<ext> plus manifest.json listing each tile's
lon/lat bounds per map view. The console lays the tiles under the Plotly map as images.
Tiles are Web Mercator; inside one tile (under 1.5 degrees) the stretch to a plain lon/lat
axis is too small to see at this scale. USGS basemaps are public domain.

    python scripts/fetch_basemap.py      # network; run on request (make basemap)
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

SERVICE = "https://basemap.nationalmap.gov/arcgis/rest/services/{service}/MapServer/tile/{z}/{y}/{x}"
# drawn bottom to top: grey hillshade, then rivers and lakes (transparent PNG)
LAYERS = [("relief", "USGSShadedReliefOnly", "jpg"), ("hydro", "USGSHydroCached", "png")]
# bounding boxes a little wider than the console's two views, so panning a bit stays covered
VIEWS = {
    "west": {"z": 9, "lon": (-83.9, -81.0), "lat": (34.8, 36.7)},
    "all": {"z": 8, "lon": (-84.2, -78.2), "lat": (34.5, 37.1)},
}
OUT = Path(__file__).resolve().parents[1] / "driftwatch" / "api" / "static" / "basemap"


def tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    r = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)


def tile_bounds(x: int, y: int, z: int) -> dict[str, float]:
    n = 2**z
    lat = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))  # noqa: E731
    return {"lon0": x / n * 360 - 180, "lon1": (x + 1) / n * 360 - 180, "lat1": lat(y), "lat0": lat(y + 1)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):  # replace any earlier style
        old.unlink()
    manifest = {"attribution": "Basemap: USGS The National Map", "layers": [l[0] for l in LAYERS], "views": {}}
    for name, v in VIEWS.items():
        z = v["z"]
        x0, y0 = tile_xy(v["lon"][0], v["lat"][1], z)  # north-west corner
        x1, y1 = tile_xy(v["lon"][1], v["lat"][0], z)  # south-east corner
        tiles = []
        for layer, service, ext in LAYERS:
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    fn = f"{layer}_{z}_{x}_{y}.{ext}"
                    path = OUT / fn
                    if not path.exists():
                        req = urllib.request.Request(SERVICE.format(service=service, z=z, x=x, y=y),
                                                     headers={"User-Agent": "driftwatch-snapshot"})
                        with urllib.request.urlopen(req, timeout=60) as r:
                            path.write_bytes(r.read())
                    tiles.append({"src": f"static/basemap/{fn}", "layer": layer,
                                  **{k: round(b, 6) for k, b in tile_bounds(x, y, z).items()}})
        manifest["views"][name] = {"z": z, "tiles": tiles}
        print(f"{name}: z{z}, {len(tiles)} tiles")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    kb = sum(p.stat().st_size for p in OUT.iterdir()) // 1024
    print(f"saved to {OUT} ({kb} KB)")


if __name__ == "__main__":
    main()
