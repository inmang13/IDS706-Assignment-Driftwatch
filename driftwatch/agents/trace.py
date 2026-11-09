"""Trace recording and replay.

Every node emits TraceEvents (core/schemas.py: run_id, site, seq, ts, node, status, payload) to an
optional asyncio queue (the API streams it as SSE) and to traces/<site>-<ts>.json. The file is
rewritten after every event, so a crashed run still leaves a readable trace.

`replay(path)` yields the same events, in order, from a saved trace.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.core.schemas import TraceEvent

REPO = Path(__file__).resolve().parents[2]


def trace_dir() -> Path:
    d = Path(os.environ.get("TRACE_DIR") or "traces")
    return d if d.is_absolute() else REPO / d


class TraceRecorder:
    def __init__(
        self,
        site: str,
        llm: str,
        queue: asyncio.Queue | None = None,
        out_dir: Path | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self.site = site
        self.llm = llm
        self.queue = queue
        self.run_id = f"{site}-{now:%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:6]}"
        # no ':' in Windows file names; microseconds so two runs in one second don't collide
        self.path = (out_dir or trace_dir()) / f"{site}-{now:%Y%m%dT%H%M%S%fZ}.json"
        self.started_at = now
        self.events: list[TraceEvent] = []
        self.final: dict[str, Any] = {}

    def emit(self, node: str, status: str, payload: dict[str, Any] | None = None) -> TraceEvent:
        ev = TraceEvent(
            run_id=self.run_id,
            site=self.site,
            seq=len(self.events),
            ts=datetime.now(UTC),
            node=node,
            status=status,
            payload=json.loads(json.dumps(payload or {}, default=str)),
        )
        self.events.append(ev)
        if self.queue is not None:
            self.queue.put_nowait(ev)
        self.write()
        return ev

    def write(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "run_id": self.run_id,
            "site": self.site,
            "llm": self.llm,
            "started_at": self.started_at.isoformat(),
            "final": self.final,
            "events": [e.model_dump(mode="json") for e in self.events],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path


def load_trace(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay(path: str | Path) -> Iterator[TraceEvent]:
    """Yield the saved events in seq order (no timing; the API adds pacing)."""
    doc = load_trace(path)
    for e in sorted(doc["events"], key=lambda e: e["seq"]):
        yield TraceEvent.model_validate(e)


DEFAULTS_FILE = "replay_defaults.json"  # {"<site>": "<trace file name>"}: Grace's pick per gauge


def latest_trace(site: str, out_dir: Path | None = None) -> Path | None:
    """The trace Replay uses: the one named in traces/replay_defaults.json, else the newest."""
    d = out_dir or trace_dir()
    defaults = d / DEFAULTS_FILE
    if defaults.exists():
        pick = json.loads(defaults.read_text(encoding="utf-8")).get(site)
        if pick and (d / pick).exists():
            return d / pick
    files = sorted(d.glob(f"{site}-*.json"))
    return files[-1] if files else None
