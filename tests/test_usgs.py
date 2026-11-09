"""Offline tests for the USGS fetcher and snapshot I/O. Never touches the network."""

import json

import httpx
import pytest

from driftwatch.modules.rating_curve import usgs


def _feature(i, site="03459500"):
    return {
        "type": "Feature",
        "id": str(i),
        "properties": {"monitoring_location_id": f"USGS-{site}", "value": str(i)},
    }


def _paged_transport(calls):
    """Two-page field-measurements; next link points at v1 like the real channel collection."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        path, q = request.url.path, request.url.params
        if path.endswith("/monitoring-locations/items"):
            assert q["id"] == "USGS-03459500"
            return httpx.Response(200, json={"features": [_feature("ml")], "links": []})
        if path.endswith("/channel-measurements/items"):
            return httpx.Response(200, json={"features": [], "links": []})
        if "cursor" in q:
            assert path.startswith("/ogcapi/v1/")
            return httpx.Response(
                200, json={"features": [_feature(3)], "links": [{"rel": "self", "href": "x"}]}
            )
        assert q["monitoring_location_id"] == "USGS-03459500"
        nxt = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/field-measurements/items?cursor=abc&f=json"
        return httpx.Response(
            200,
            json={"features": [_feature(1), _feature(2)], "links": [{"rel": "next", "href": nxt}]},
        )

    return httpx.MockTransport(handler)


def test_fetch_follows_next_links_verbatim():
    calls = []
    client = usgs.make_client(api_key="", transport=_paged_transport(calls))
    data = usgs.fetch_site("03459500", client)
    assert usgs.row_counts(data) == {
        "field-measurements": 3,
        "channel-measurements": 0,
        "monitoring-locations": 1,
    }
    assert any("/ogcapi/v1/" in c and "cursor=abc" in c for c in calls)


def test_empty_required_collection_refuses():
    def handler(request):
        return httpx.Response(200, json={"features": [], "links": []})

    client = usgs.make_client(api_key="", transport=httpx.MockTransport(handler))
    with pytest.raises(usgs.SnapshotError):
        usgs.fetch_site("03459500", client)


def test_retry_on_429(monkeypatch):
    monkeypatch.setattr(usgs.time, "sleep", lambda s: None)
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"features": [_feature(1)], "links": []})

    client = usgs.make_client(api_key="", transport=httpx.MockTransport(handler))
    assert len(usgs.fetch_collection(client, "field-measurements", "03459500")) == 1
    assert hits["n"] == 2


def test_snapshot_round_trip_utf8(tmp_path):
    data = {
        "site": "02085000",
        "fetched_at": "2026-11-07T00:00:00Z",
        "api_base": usgs.API_BASE,
        "collections": {
            "field-measurements": [_feature(1)],
            "channel-measurements": [],
            "monitoring-locations": [
                {"properties": {"monitoring_location_name": "Eno R — Hillsborough"}}
            ],
        },
    }
    path = usgs.write_snapshot(data, tmp_path)
    assert path.name == "02085000.json"
    assert not list(tmp_path.glob("*.tmp"))
    assert usgs.load_snapshot("02085000", tmp_path) == data
    assert "—" in path.read_text(encoding="utf-8")


def test_load_snapshot_missing_collection(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"site": "x", "collections": {}}), encoding="utf-8")
    with pytest.raises(usgs.SnapshotError):
        usgs.load_snapshot("x", tmp_path)


def test_main_refuses_without_live(capsys):
    assert usgs.main(["--source", "snapshot", "--sites", "03459500"]) == 2
