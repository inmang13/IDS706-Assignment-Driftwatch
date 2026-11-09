"""Fetch raw USGS Water Data OGC API features for a site and snapshot them to disk.

Snapshot is the default data source. Live USGS is used only with --source live.

Snapshot layout (data/snapshot/<site>.json):
    {"site": "03459500", "fetched_at": "...Z", "api_base": "...",
     "collections": {"field-measurements": [features...],
                     "channel-measurements": [features...],
                     "monitoring-locations": [features...]}}
Features are stored exactly as the API returned them (values are strings).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

API_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0"
PAGE_LIMIT = 10000
COLLECTIONS = ("field-measurements", "channel-measurements", "monitoring-locations")
# monitoring-locations rejects monitoring_location_id (HTTP 400); it filters on id.
SITE_FILTER = {
    "field-measurements": "monitoring_location_id",
    "channel-measurements": "monitoring_location_id",
    "monitoring-locations": "id",
}
# Collections that must not come back empty; channel-measurements may legitimately be empty.
REQUIRED_NONEMPTY = ("field-measurements", "monitoring-locations")

SITES = (
    "03459500", "03455000", "03446000", "03451500",
    "03451000", "03463300", "03479000", "02085000",
)  # fmt: skip

SNAPSHOT_DIR = Path(__file__).resolve().parents[3] / "data" / "snapshot"

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
MAX_PAGES = 1000


class SnapshotError(RuntimeError):
    pass


def make_client(
    api_key: str | None = None, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    headers = {"User-Agent": "driftwatch/0.1 (hackathon research)"}
    key = api_key if api_key is not None else os.environ.get("USGS_API_KEY", "")
    if key:
        headers["X-Api-Key"] = key
    return httpx.Client(headers=headers, timeout=60.0, transport=transport, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> dict:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == MAX_ATTEMPTS:
                raise
        else:
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                return resp.json()
            if attempt == MAX_ATTEMPTS:
                resp.raise_for_status()
        time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def _next_href(page: dict) -> str | None:
    for link in page.get("links", []):
        if link.get("rel") == "next":
            return link.get("href")
    return None


def fetch_collection(
    client: httpx.Client, collection: str, site: str, base: str = API_BASE
) -> list[dict]:
    """All features for one site in one collection, following `next` links verbatim."""
    url: str | None = f"{base}/collections/{collection}/items"
    params: dict[str, Any] | None = {
        "f": "json",
        SITE_FILTER[collection]: f"USGS-{site}",
        "limit": PAGE_LIMIT,
    }
    features: list[dict] = []
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        page = _get_json(client, url, params)
        features.extend(page.get("features", []))
        url = _next_href(page)
        if url is None:
            return features
        if url in seen:
            raise SnapshotError(f"{collection} {site}: next link loops ({url})")
        seen.add(url)
        params = None  # the next href already carries every query parameter
    raise SnapshotError(f"{collection} {site}: more than {MAX_PAGES} pages")


def fetch_site(site: str, client: httpx.Client | None = None, base: str = API_BASE) -> dict:
    own = client is None
    client = client or make_client()
    try:
        collections = {c: fetch_collection(client, c, site, base) for c in COLLECTIONS}
    finally:
        if own:
            client.close()
    for c in REQUIRED_NONEMPTY:
        if not collections[c]:
            raise SnapshotError(f"{site}: {c} returned 0 features; refusing to write snapshot")
    return {
        "site": site,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "api_base": base,
        "collections": collections,
    }


def snapshot_path(site: str, snapshot_dir: Path | None = None) -> Path:
    return (snapshot_dir or SNAPSHOT_DIR) / f"{site}.json"


def write_snapshot(data: dict, snapshot_dir: Path | None = None) -> Path:
    """Atomic write: a failed run never clobbers an existing good snapshot."""
    path = snapshot_path(data["site"], snapshot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def load_snapshot(site: str, snapshot_dir: Path | None = None) -> dict:
    path = snapshot_path(site, snapshot_dir)
    if not path.exists():
        raise FileNotFoundError(f"no snapshot for {site} at {path}; run: make snapshot SOURCE=live")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    missing = [c for c in COLLECTIONS if c not in data.get("collections", {})]
    if missing:
        raise SnapshotError(f"{path} missing collections: {missing}")
    return data


def row_counts(data: dict) -> dict[str, int]:
    return {c: len(data["collections"][c]) for c in COLLECTIONS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snapshot USGS OGC API features per site.")
    ap.add_argument("--source", choices=("snapshot", "live"), default="snapshot")
    ap.add_argument("--sites", nargs="+", default=list(SITES))
    args = ap.parse_args(argv)

    if args.source != "live":
        print("Refusing to fetch: snapshot is the default source. Re-run with SOURCE=live.")
        return 2

    failures = []
    rows = []
    with make_client() as client:
        for site in args.sites:
            try:
                data = fetch_site(site, client)
            except (httpx.HTTPError, SnapshotError) as exc:
                failures.append(site)
                print(f"{site}: FAILED ({exc}); existing snapshot left untouched", file=sys.stderr)
                continue
            path = write_snapshot(data)
            rows.append((site, row_counts(data), path.stat().st_size))

    print(f"{'site':<10} {'field-meas':>11} {'channel-meas':>13} {'mon-loc':>8} {'MB':>6}")
    for site, counts, size in rows:
        print(
            f"{site:<10} {counts['field-measurements']:>11} {counts['channel-measurements']:>13}"
            f" {counts['monitoring-locations']:>8} {size / 1e6:>6.2f}"
        )
    if failures:
        print(f"failed: {' '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
