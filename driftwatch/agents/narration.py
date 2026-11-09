"""Narrator facts, the fixed sentences built from them, and the narration guard.

Every number and every claim the narrator may use is computed here, in code, from the triage
facts and the evidence tools. The LLM only arranges these into prose; the fallback template in
fallbacks.narrate uses the same sentences. Channel area and velocity are evidence only: they feed
the cross-check sentence and are never used to predict flow.

The guard (check_text) enforces the hard rules on any narration text: banned words and patterns,
the 200-word cap, the closing "Rating confidence N/100 (Band)." sentence, and the open-cause rule
(no mechanism words in DriftWatch's own conclusion; the field note's meaning and a cached lead are
labelled sentences, so they are stripped before that check).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from statistics import median
from typing import Any

from driftwatch.agents import tools

MAX_WORDS = 200
HELENE_DATE = datetime(2024, 9, 27, tzinfo=UTC)
AGREE_POINTS = 15.0  # the area x velocity check agrees when within this many % points of the step


# Fixed meaning of each field note, keyed by how the note starts (lower case). Each entry: the
# sentence the narration uses, and the residual sign the note implies (negative = measurements
# below the rating, i.e. a higher water level for a given flow rate).
NOTE_MEANING: dict[str, tuple[str, str]] = {
    "fill control changed": (
        (
            "In the note's terms, gravel built up on the control (the riffle just downstream "
            "that sets the water level), so water backs up at the gauge: deeper, more area, much "
            "lower velocity."
        ),
        "negative",
    ),
    "scour control changed": (
        (
            "In the note's terms, the control (the riffle just downstream that sets the water "
            "level) eroded, so a given flow rate passes at a lower water level."
        ),
        "positive",
    ),
    "debris": (
        (
            "In the note's terms, debris blocked the control (the riffle just downstream that "
            "sets the water level), raising the level until it clears."
        ),
        "negative",
    ),
}


def word_count(text: str) -> int:
    """Words in the text; bare symbols ('%', '=', '×') are not words."""
    return sum(1 for w in text.split() if re.search(r"[A-Za-z0-9]", w))


def _fmt_cfs(q: float) -> str:
    q = abs(q)
    if q >= 100:
        q = round(q, -1) if q < 10000 else round(q, -2)
    return f"{q:,.0f}"


def _date(s: str | None) -> str | None:
    return s[:10] if s else None


def _note_cause(note: str) -> str | None:
    from driftwatch.modules.rating_curve import causes as catalog

    c = catalog.cause_for_note(note)
    return c.key if c else None


def note_lookup(note: str | None) -> tuple[str, str] | None:
    n = (note or "").strip().lower()
    for key, val in NOTE_MEANING.items():
        if n.startswith(key):
            return val
    return None


def _pick_note(visits: list[dict], change_date: str | None) -> dict | None:
    """The field note to explain: the note at the change visit if it has a lookup meaning, else
    the earliest 'control changed' note since the reference window, else the latest note with a
    lookup meaning. None when no note has one."""
    known = [v for v in visits if note_lookup(v.get("note"))]
    if not known:
        return None
    if change_date:
        at = [v for v in known if v["time"][:10] == change_date]
        if at:
            return at[0]
    control = [v for v in known if "control changed" in v["note"].lower()]
    return control[0] if control else known[-1]


def _post_change_stage(site: str, change_time: str) -> float | None:
    t0 = datetime.fromisoformat(change_time)  # 3.11 reads a trailing Z
    hs = [m.stage_ft for m in tools.dataset(site).measurements if not m.excluded and m.time >= t0]
    return float(median(hs)) if hs else None


def narration_facts(facts: dict[str, Any], context: list[dict] | None = None) -> dict[str, Any]:
    """Every fact the narration may state, computed in code. Keys are None when not available.

    change_date            top_shift.time (date)
    level_change_ft        |top_shift.size_ft|; level_word 'higher' (size_ft < 0) or 'lower'
    at_stage_ft            channel_geometry_trend at_stage_ft, else median post-change stage
    curve_cfs              the base rating's flow at at_stage_ft
    flow_change_cfs / _pct curve_cfs x top_shift.size_pct (signed; < 0 = less flow than the curve)
    area_change_pct, velocity_change_pct   evidence only
    check_pct              ((1 + area%) x (1 + velocity%) - 1) x 100
    check_agrees           same sign as the step and within AGREE_POINTS of it
    flood                  largest measured flow between the last visit before and the first after
    helene                 the last visit before the change is before 2024-09-27 and the change
                           visit (the first tested visit after it) is after it, i.e. the change
                           was first measured at the first visit after the storm
    note                   the field note explained, its date, meaning and whether it fits the data
    """
    t = facts["triage"]
    site = t["site"]
    shift = t.get("top_shift")
    ch = facts.get("channel_geometry") or {}
    fc = facts.get("flood_context") or {}
    meta = facts.get("site_metadata") or {}
    f: dict[str, Any] = {
        "site": site,
        "site_name": t.get("site_name") or site,
        "river_name": _river_name(t.get("site_name") or site),
        "county": meta.get("county_name"),
        "band": t["band"],
        "score": round(t["score"]),
        "rating_sentence": f"Rating confidence {round(t['score'])}/100 ({t['band']}).",
        "direction_phrase": t["direction_phrase"],
        "published_flows": t["published_flows"],
        "off_by_pct": round(t["off_by_pct"]),
        "change_date": None,
        "level_change_ft": None,
        "level_word": None,
        "step_pct": None,
        "at_stage_ft": None,
        "curve_cfs": None,
        "flow_change_cfs": None,
        "flow_change_pct": None,
        "area_change_pct": None,
        "velocity_change_pct": None,
        "check_pct": None,
        "check_agrees": None,
        "flood": None,
        "window": None,
        "helene": False,
        "note": None,
        "lead": None,
    }
    if shift:
        cd = _date(shift["time"])
        f["change_date"] = cd
        f["level_change_ft"] = round(abs(shift["size_ft"]), 2)
        f["level_word"] = "higher" if shift["size_ft"] < 0 else "lower"
        f["step_pct"] = round(shift["size_pct"], 1)
        h0 = ch.get("at_stage_ft") if ch.get("sufficient") else None
        if h0 is None:
            h0 = _post_change_stage(site, shift["time"])
        if h0 is not None:
            q = tools._relationship(site).discharge(h0)
            if not math.isnan(q):
                f["at_stage_ft"] = round(h0, 2)
                f["curve_cfs"] = float(q)
                f["flow_change_cfs"] = float(q) * shift["size_pct"] / 100
                f["flow_change_pct"] = round(shift["size_pct"])
    if ch.get("sufficient"):
        da, dv = ch["area_change_pct"], ch["velocity_change_pct"]
        f["area_change_pct"], f["velocity_change_pct"] = round(da), round(dv)
        f["check_pct"] = round(((1 + da / 100) * (1 + dv / 100) - 1) * 100, 1)
        if f["step_pct"] is not None:
            same = (f["check_pct"] > 0) == (f["step_pct"] > 0)
            f["check_agrees"] = same and abs(f["check_pct"] - f["step_pct"]) <= AGREE_POINTS
    if fc:
        f["window"] = [
            _date(fc.get("last_pre_shift_visit")),
            _date(fc.get("first_post_shift_visit")),
        ]
        pk = fc.get("peak")
        if pk:
            f["flood"] = {
                "date": _date(pk["time"]),
                "discharge_cfs": pk["discharge_cfs"],
                "rated": pk.get("rated"),
                "storm_gauging": bool(pk.get("helene_excluded")),
            }
        f["helene"] = helene_between(*f["window"], f["change_date"])
    visits = (facts.get("field_notes") or {}).get("visits") or []
    v = _pick_note(visits, f["change_date"])
    if v:
        meaning, sign = note_lookup(v["note"])
        data_sign = t["direction"]
        f["note"] = {
            "note": v["note"],
            "date": _date(v["time"]),
            "meaning": meaning,
            "implies": sign,
            "agrees_with_data": sign == data_sign,
            "cause": _note_cause(v["note"]),
        }
    f["lead"] = pick_lead(context, f["helene"])
    return f


LEAD_ORDER = ("construction", "dam", "usgs_report", "storm", "other")
OLD_REPORT_BEFORE = 2015  # a USGS report dated before this year is too old to be a lead


def pick_lead(items: list[dict] | None, helene: bool) -> dict | None:
    """One cached web item for the 'Possible lead' sentence: construction, then dam, then USGS
    report, storm, other. Skipped: items a reviewer marked `reviewed: false`; USGS reports dated
    before 2015 (OLD_REPORT_BEFORE; undated reports are kept); a claim naming Helene unless
    `helene` is true (rule 4); and one whose sentence would trip the voice guard."""
    ok = []
    for it in items or []:
        if not it.get("url") or not it.get("claim") or not it.get("source_title"):
            continue
        if it.get("reviewed") is False:
            continue
        year = re.match(r"\s*(\d{4})", str(it.get("date") or ""))
        if it.get("kind") == "usgs_report" and year and int(year.group(1)) < OLD_REPORT_BEFORE:
            continue
        if not helene and "helene" in (it["claim"] + it["source_title"]).lower():
            continue
        if banned(lead_sentence(it)):
            continue
        ok.append(it)
    rank = {k: i for i, k in enumerate(LEAD_ORDER)}
    ok.sort(key=lambda it: rank.get(it.get("kind"), len(rank)))
    return ok[0] if ok else None


def lead_sentence(lead: dict) -> str:
    return f"Possible lead: {lead['claim'].rstrip('.')} ({lead['source_title']})."


def helene_between(lo: str | None, hi: str | None, change_date: str | None) -> bool:
    """True when Helene (2024-09-27) falls between the last visit before the change (lo) and the
    change visit (hi), so the change was first measured at the first visit after the storm."""
    if not (lo and hi and change_date) or hi != change_date:
        return False
    storm = HELENE_DATE.date().isoformat()
    return lo < storm < hi


def helene_event(f: dict[str, Any]) -> str:
    """The fixed Helene event sentence (used verbatim by the template and required by the
    guard)."""
    lo, hi = f["window"]
    passed = f"Hurricane Helene (2024-09-27) passed between the {lo} and {hi} visits"
    fl = f["flood"]
    if not fl:
        return f"{passed}; no gauging was made during the storm."
    if fl["storm_gauging"]:
        # storm gaugings exist (rated Poor, left out of the drift test): saying "no gauging was
        # made" would contradict the peak, so the clause names them instead
        return (
            f"{passed}; the storm gaugings were rated {fl['rated']}, the largest "
            f"{_fmt_cfs(fl['discharge_cfs'])} cfs on {fl['date']}."
        )
    return (
        f"{passed}; no gauging was made during the storm, and the largest flow gauged between "
        f"the visits was {_fmt_cfs(fl['discharge_cfs'])} cfs on {fl['date']}."
    )


def _river_name(site_name: str) -> str:
    """'PIGEON RIVER NEAR HEPCO, NC' -> 'the Pigeon River near Hepco'."""
    words = []
    for w in site_name.split(",")[0].split():
        lw = w.lower()
        words.append(lw if lw in ("near", "at", "above", "below", "of", "nr") else w.capitalize())
    return "the " + " ".join(words)


# --------------------------------------------------------------------------- fixed sentences


def _pct(x: float) -> str:
    return f"{x:+.0f} %"


def moved(x: float) -> str:
    """A signed % change as words: 'rose 8 %', 'fell 22 %', 'did not change'."""
    n = round(abs(x))
    if n == 0:
        return "did not change"
    return f"{'rose' if x > 0 else 'fell'} {n} %"


def step_noun(x: float) -> str:
    """'the 46 % rise' / 'the 26 % drop'."""
    return f"the {round(abs(x))} % {'rise' if x > 0 else 'drop'}"


def short_cause(key: str | None) -> str:
    """'fill', 'scour', 'datum change': the catalog key in plain words."""
    return (key or "").replace("_", " ")


def note_vs_data(note_sign: str, direction_phrase: str) -> str:
    """The note-vs-data sentence: what the note implies against where the data sit."""
    want = {"positive": "above", "negative": "below"}.get(note_sign, "off")
    return (
        f"That disagrees with the data: the note implies measurements {want} the rating, but "
        f"they sit {direction_phrase}."
    )


def sentences(
    f: dict[str, Any],
    cause_label: str | None,
    status: str,
    check: str | None,
    confidence: float | None = None,
    disagreement_rule: str | None = None,
    final_key: str | None = None,
) -> dict[str, str | None]:
    """The fixed sentences of a narration, by role. None when the fact behind it is missing."""
    name = f"{f['river_name']}, USGS {f['site']}"
    s: dict[str, str | None] = {}
    if status == "none":
        s["measured"] = (
            f"Field measurements at {name}, have averaged {f['off_by_pct']} % "
            f"{f['direction_phrase']}, and DriftWatch found no lasting shift since the reference "
            "window, so published flows can be used as they are."
        )
        s["rating"] = f["rating_sentence"]
        return s
    lead_in = (
        f"Since the {f['change_date']} visit, measurements" if f["change_date"] else "Measurements"
    )
    s["measured"] = (
        f"{lead_in} at {name}, sit {f['off_by_pct']} % "
        f"{f['direction_phrase']}, so published flows run that much {f['published_flows']}."
    )
    s["level"] = None
    if f["level_change_ft"] is not None and f["curve_cfs"] is not None:
        less = "less" if f["flow_change_cfs"] < 0 else "more"
        s["level"] = (
            f"For a given flow rate, the river stands {f['level_change_ft']:.2f} ft "
            f"{f['level_word']} than the curve predicts; at a stage of {f['at_stage_ft']:.2f} ft "
            f"it carries about {_fmt_cfs(f['flow_change_cfs'])} cfs "
            f"({abs(f['flow_change_pct'])} %) {less} than the curve's "
            f"{_fmt_cfs(f['curve_cfs'])} cfs."
        )
    n = f["note"]
    s["note"] = None
    s["note_meaning"] = None
    if n:
        # only a disagreement needs saying; agreement is implied by the next sentences
        fits = "" if n["agrees_with_data"] else " That disagrees with the data."
        s["note"] = f"The hydrographer noted \"{n['note']}\" on {n['date']}."
        s["note_meaning"] = f"{n['meaning']}{fits}"
    s["check"] = None
    if f["check_pct"] is not None and f["step_pct"] is not None:
        at = f["at_stage_ft"] or 0.0
        verdict = "agrees with" if f["check_agrees"] else "does not back up"
        s["check"] = (
            # the level sentence already names the stage (same at_stage_ft); point back to it
            f"After the change, at "
            f"{'that stage' if s.get('level') else f'a stage of {at:.2f} ft'}, "
            f"area {moved(f['area_change_pct'])} and velocity "
            f"{moved(f['velocity_change_pct'])}, so the flow rate there "
            f"{moved(f['check_pct']).replace(' ', ' about ', 1)}, which {verdict} "
            f"{step_noun(f['step_pct'])} in measured flow rate."
        )
    lo, hi = f["window"] or (None, None)
    if f["helene"]:
        s["event"] = helene_event(f)
    elif f["flood"]:
        between = f" between the {lo} and {hi} visits" if lo and hi else ""
        s["event"] = (
            f"The largest flow measured{between} was "
            f"{_fmt_cfs(f['flood']['discharge_cfs'])} cfs on {f['flood']['date']}."
        )
    else:
        between = f" between the {lo} and {hi} visits" if lo and hi else ""
        s["event"] = f"No gauging falls{between}, so no measured high flow explains it."
    s["lead"] = None
    if f["lead"]:
        s["lead"] = lead_sentence(f["lead"])
    if status == "open":
        s["conclusion"] = "No field note confirms what changed, so the cause remains open."
    elif status == "disagreement" and disagreement_rule == "note_sign" and f.get("note"):
        s["conclusion"] = (
            f"DriftWatch's agents rank {short_cause(final_key)} first "
            f"({confidence * 100:.0f} %); the hydrographer's note says "
            f"{short_cause(f['note']['cause'])}; the two disagree, so the cause is not settled."
        )
    elif status == "disagreement":
        s["conclusion"] = (
            f"DriftWatch's agents rank {cause_label} first ({confidence * 100:.0f} %), but the "
            "Skeptic is under 60 % sure."
        )
    else:
        conf = f" ({confidence * 100:.0f} %)" if confidence is not None else ""
        s["conclusion"] = (
            f"DriftWatch's agents rank {cause_label} first{conf}; the Skeptic accepted it."
        )
    s["double_check"] = f"Double-check: {check}" if check else None
    s["rating"] = f["rating_sentence"]
    return s


ORDER = (
    "measured",
    "level",
    "note",
    "note_meaning",
    "check",
    "event",
    "lead",
    "conclusion",
    "double_check",
    "rating",
)


def join(s: dict[str, str | None]) -> str:
    """The sentences in report order. The optional lead is dropped if it would break the cap."""
    text = " ".join(s[k] for k in ORDER if s.get(k))
    if word_count(text) > MAX_WORDS and s.get("lead"):
        text = " ".join(s[k] for k in ORDER if s.get(k) and k != "lead")
    return text


# --------------------------------------------------------------------------- guard

# em/en dashes; '--' used as a dash. A spaced hyphen stays legal: field notes read "Debris - Light".
DASHES = re.compile(r"[—–]|\s--\s")
BANNED_PHRASES = re.compile(
    r"\bnot just\b|\bnot only\b|\bisn'?t just\b|\bit'?s not\b[^.]{0,80}?\bit'?s\b"
    r"|\bnot\b[^.;,]{1,60},\s*but\b"
    r"|\bin summary\b|\boverall\b|\bultimately\b|\bit'?s worth noting\b|\bimportantly\b"
    r"|\bnotably\b|\bin other words\b"
    r"|\bdelv\w*|\bcrucial\w*|\bpivotal\b|\brobust\w*|\bseamless\w*|\bleverag\w*|\blandscapes?\b"
    r"|\btapestr\w*|\btestament\b|\bunderscor\w*|\bnavigat\w*|\brealms?\b|\bjourneys?\b"
    r"|\bamount of water\b|\bthe team\b|\bsame flow\b|\bspeed\b",
    re.IGNORECASE,
)
# a list of exactly three adjectives: 'X, Y(,) and Z' where each word has an adjective suffix
_ADJ = r"[a-z]+(?:ive|ous|ful|able|ible|al|ic|ent|ant|less|ary|ory|ish|y)"
ADJ_TRIAD = re.compile(rf"\b{_ADJ},\s+{_ADJ},?\s+and\s+{_ADJ}\b", re.IGNORECASE)
MARKUP = re.compile(r"\*\*|__|^\s*#|^\s*[-*•]\s|\n\s*[-*•]\s|\n\s*#", re.MULTILINE)
UNSPACED_UNIT = re.compile(r"\d(?:cfs|ft|%)")
SIGNED_NUMBER = re.compile(r"(?<![\w-])[+−-]\d[\d,.]*\s?(?:%|cfs|ft)")


def banned(text: str) -> str | None:
    """The first banned word or pattern in the text, or None. Voice rules only."""
    if m := DASHES.search(text):
        return f"dash used as punctuation ({m.group(0)!r})"
    if "!" in text:
        return "exclamation mark"
    if "?" in text:
        return "question mark (rhetorical question)"
    if m := BANNED_PHRASES.search(text):
        return f"banned phrase {m.group(0)!r}"
    if m := ADJ_TRIAD.search(text):
        return f"list of three adjectives {m.group(0)!r}"
    if MARKUP.search(text):
        return "heading, bullet or bold markup"
    if m := SIGNED_NUMBER.search(text):
        return f"signed number; say rose/fell instead ({m.group(0)!r})"
    if m := UNSPACED_UNIT.search(text):
        return f"unit not spaced from its number ({m.group(0)!r})"
    return None


def strip_labelled(text: str, f: dict[str, Any] | None) -> str:
    """Text minus the parts that are labelled as someone else's: the quoted field note, the
    note's fixed meaning, and the 'Possible lead' sentence. Used before the open-cause check."""
    out = text
    if f and f.get("note"):
        out = out.replace(f["note"]["meaning"], " ")
        out = out.replace(f'"{f["note"]["note"]}"', " ")
        out = out.replace(f["note"]["note"], " ")
    if f and f.get("lead"):
        out = out.replace(lead_sentence(f["lead"]), " ")
    return out


def _structure(text: str, f: dict[str, Any]) -> str | None:
    """Rules (3), (4) for a gauge with a final call: the
    check sentence's verdict words, and the event wording."""
    if f.get("check_pct") is not None and f.get("step_pct") is not None:
        want = "which agrees with" if f["check_agrees"] else "which does not back up"
        if want not in text:
            return f"the check sentence must say '{want}'"
    if f.get("helene"):
        want = helene_event(f)
        if want not in text:
            return f"the Helene event sentence must appear verbatim: '{want}'"
    if f.get("change_date") and f.get("helene") and f.get("flood"):
        q = f"{_fmt_cfs(f['flood']['discharge_cfs'])} cfs"
        if q not in text:
            return f"the event sentence must give the largest measured flow ({q})"
    if f.get("change_date") and not f.get("helene"):
        if f.get("flood"):
            q = f"{_fmt_cfs(f['flood']['discharge_cfs'])} cfs"
            if q not in text:
                return f"the event sentence must give the largest measured flow ({q})"
        elif "no measured high flow explains it" not in text.lower():
            return "the event sentence must say 'no measured high flow explains it'"
    return None


def check_text(text: str, f: dict[str, Any] | None, status: str | None = None) -> str | None:
    """None if the narration text passes the hard rules, else why not."""
    from driftwatch.agents.fallbacks import MECHANISM_WORDS  # avoid an import cycle

    words = word_count(text)
    if words > MAX_WORDS:
        return f"{words} words > {MAX_WORDS}"
    if f is not None and not text.rstrip().endswith(f["rating_sentence"]):
        return f"must end with '{f['rating_sentence']}'"
    if bad := banned(text):
        return bad
    if f is not None and not f.get("helene") and "helene" in text.lower():
        return "Helene may be named only when it falls between the last visit and the change visit"
    if status == "open" and (m := MECHANISM_WORDS.search(strip_labelled(text, f))):
        return f"an open cause must not name a mechanism ('{m.group(0)}')"
    if f is not None and status not in (None, "none") and (bad := _structure(text, f)):
        return bad
    needs_note = f is not None and f.get("note") and status not in (None, "none")
    if needs_note and f["note"]["meaning"] not in text:
        return "the field note's fixed meaning must appear verbatim"
    return None
