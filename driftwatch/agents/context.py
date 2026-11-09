"""Event context from the web, cached per site in data/context/<site>.json.

load() is what the evidence collector calls at run time: it only reads the cached file and never
searches. The search side (`make context SITE=...`, i.e. `python -m driftwatch.agents.context`)
is never called by tests or by an agent run.

Search: Gemini on Vertex with Google Search grounding. Queries are built in code from the site
name, river, county and the window between the last visit before and the first visit after the
change. Each finding the model writes is kept only if a grounding chunk supports it; the chunk's
redirect link is resolved to the real URL and the page's own <title> is fetched. Items whose claim
and title don't name this river or county are dropped. Every item is a lead to check by hand.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTEXT_DIR = Path(__file__).resolve().parents[2] / "data" / "context"
KINDS = ("storm", "dam", "construction", "usgs_report", "other")
MAX_ITEMS = 5
MAX_CLAIM_WORDS = 25


def path(site: str, root: Path | None = None) -> Path:
    return (root or CONTEXT_DIR) / f"{site}.json"


def load(site: str, root: Path | None = None) -> dict[str, Any] | None:
    """The cached context for a site, or None when there is no file. Items without a URL are
    dropped here too, so a hand-edited file can't slip one through."""
    p = path(site, root)
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    items = [i for i in doc.get("items", []) if i.get("url") and i.get("claim")]
    return {**doc, "items": items, "source_file": p.name}


# --------------------------------------------------------------------------- text hygiene


def clean_text(s: str, max_words: int | None = None) -> str:
    """Plain one-line text that passes the narration guard's punctuation rules: en dash between
    digits -> hyphen, other dashes -> comma, no | ? ! or quotes, no parentheses."""
    s = html.unescape(s or "")
    s = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", "-", s)
    s = re.sub(r"\s*[—–]\s*|\s+--\s+", ", ", s)
    s = re.sub(r"[|?!\"“”()\[\]]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;:")
    if max_words:
        words = s.split()
        if len(words) > max_words:
            s = " ".join(words[:max_words]).rstrip(",;:")
    return s


def clean_title(t: str) -> str:
    """Page title minus the site-name suffix ('X | NCDOT', 'X - WBIR')."""
    t = html.unescape(t or "").strip()
    t = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[^-]+$)", t)[0]
    return clean_text(t, 12).rstrip(" -")


# --------------------------------------------------------------------------- search side


def _site_terms(site: str) -> dict[str, Any]:
    from driftwatch.agents import narration, tools

    meta = tools.site_metadata(site)
    fc = tools.flood_context(site, None)
    name = meta.get("monitoring_location_name") or site
    river = narration._river_name(name)[4:]  # 'Pigeon River near Hepco'
    core = re.split(r"\s+(?:near|at|above|below|nr)\s+", river)[0]  # 'Pigeon River'
    place = river[len(core) :].strip()
    county = meta.get("county_name") or ""
    return {
        "site": site,
        "name": name,
        "river": core,
        "river_key": core.replace(" River", "").replace(" Creek", "").strip(),
        "place": place,
        "county": county,
        "county_key": county.replace(" County", "").strip(),
        "state": meta.get("state_name") or "",
        "lo": (fc.get("last_pre_shift_visit") or "")[:10],
        "hi": (fc.get("first_post_shift_visit") or "")[:10],
    }


def queries(t: dict[str, Any]) -> list[tuple[str, str]]:
    """(kind hint, question) for one site, built from the site's own facts."""
    where = f"the {t['river']} {t['place']} in {t['county']}, {t['state']}"
    years = sorted({t["lo"][:4], t["hi"][:4]} - {""})
    span = "-".join(years) if years else "recent years"
    return [
        ("storm", f"Storms or floods that affected {where} between {t['lo']} and {t['hi']}."),
        (
            "construction",
            (
                f"Dams, dam removals, bridge construction or channel construction on {where}, near "
                f"USGS streamgage {t['site']}, in {span}."
            ),
        ),
        (
            "usgs_report",
            (
                f"USGS publications or reports about streamgage {t['site']} ({t['name']}) or about "
                f"the {t['river']} in {t['state']}."
            ),
        ),
    ]


ASK = """{question}

Answer with up to 3 findings from your search results, one per line, in exactly this form:
kind | date | claim
kind is one of storm, dam, construction, usgs_report, other. date is YYYY-MM-DD, YYYY-MM or
YYYY. claim is one plain factual sentence under 25 words that names the {river} or {county}.
Write nothing else. If you find nothing about this river or county, write NONE."""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


def _resolve(uri: str) -> tuple[str | None, str | None, str]:
    """Follow the grounding redirect to the real page; return (final url, page <title>, page
    text). The text is what the river/county filter checks, so a claim the model wrote can't
    vouch for itself. PDFs and blocked pages give empty text and are dropped by that filter."""
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (DriftWatch context cache)"}
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers=headers) as c:
            r = c.get(uri)
            url = str(r.url)
            title, text = None, ""
            if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                page = r.text[:600000]
                m = re.search(r"<title[^>]*>(.*?)</title>", page, re.DOTALL | re.IGNORECASE)
                title = m.group(1).strip() if m else None
                text = re.sub(r"<[^>]+>", " ", page)
            return url, title, text
    except Exception:  # noqa: BLE001 - unreachable page: keep nothing from it
        return None, None, ""


def _about_site(t: dict[str, Any], *texts: str) -> bool:
    blob = " ".join(x or "" for x in texts).lower()
    keys = [t["river_key"].lower(), t["county_key"].lower()]
    return any(k and k in blob for k in keys)


def search_site(site: str) -> dict[str, Any]:
    from google.cloud.aiplatform_v1beta1.types import Tool as VertexTool

    from driftwatch.agents import llm

    t = _site_terms(site)
    chat, label = llm._gemini()
    items: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    resolved: dict[str, tuple[str | None, str | None, str]] = {}
    for hint, q in queries(t):
        msg = ASK.format(question=q, river=t["river"], county=t["county"])
        r = chat.invoke(msg, tools=[VertexTool(google_search={})])
        text = _text(r.content)
        gm = r.response_metadata.get("grounding_metadata") or {}
        chunks = gm.get("grounding_chunks") or []
        supports = gm.get("grounding_supports") or []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or parts[0].upper() == "NONE":
                continue
            kind = parts[0].lower() if parts[0].lower() in KINDS else hint
            date, claim = parts[1], " | ".join(parts[2:])
            idx = [
                i
                for s in supports
                if (s.get("segment") or {}).get("text", "").strip()
                and s["segment"]["text"].strip()[:60] in line
                for i in s.get("grounding_chunk_indices") or []
            ]
            if not idx:
                dropped.append({"claim": claim, "why": "no grounding chunk supports it"})
                continue
            web = (chunks[idx[0]] or {}).get("web") or {}
            uri = web.get("uri")
            if uri not in resolved:
                resolved[uri] = _resolve(uri) if uri else (None, None, "")
            url, page_title, page_text = resolved[uri]
            if not url:
                dropped.append({"claim": claim, "why": "source link did not resolve"})
                continue
            if page_title and re.search(
                r"error|access denied|just a moment|forbidden", page_title, re.IGNORECASE
            ):
                page_title = None  # a block page, not the source's title
            title = clean_title(page_title or web.get("title") or "")
            if not _about_site(t, title, page_text):  # the page, not the model's claim
                dropped.append({"claim": claim, "url": url, "why": "not about this river/county"})
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            items.append(
                {
                    "kind": kind,
                    "claim": clean_text(claim, MAX_CLAIM_WORDS).rstrip(".") + ".",
                    "date": date,
                    "url": url,
                    "source_title": title or web.get("title") or url,
                    "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
    return {
        "site": site,
        "site_name": t["name"],
        "model": label,
        "window": [t["lo"], t["hi"]],
        "queries": [q for _, q in queries(t)],
        "note": "Leads from a web search, cached; each is a lead to check, never a cause.",
        "items": items[:MAX_ITEMS],
        "dropped": dropped,
    }


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(description="Cache web leads for one gauge")
    ap.add_argument("--site", required=True)
    a = ap.parse_args(argv)
    doc = search_site(a.site)
    out = path(a.site)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{a.site}: {len(doc['items'])} items kept, {len(doc['dropped'])} dropped -> {out}")
    for i in doc["items"]:
        print(f"  [{i['kind']}] {i['claim']} ({i['source_title']}) {i['url']}")


if __name__ == "__main__":
    main()
