"""Media resolution (v4 contract, plan time): the directed script's media B-roll cues -> media.json, before render.

media.json (next to directed.json; a Studio project keeps one at its root, shared by builds and previews):
  {"version": 1, "title": ..., "items": {slot: {
      "slot", "shot", "at", "query", "media": "image"|"video", "providers": [...], "treatment", "layout", "paid_ok",
      "status": "picked" | "swapped" | "rejected" | "unresolved" | "awaiting_approval" | "approved",
      "chosen": Candidate + {"path": local file, "cutout"?: png, "sticker"?: png, "segment"?: [in, out]} | null,
      "alternates": [Candidate...], "notes": [...]}},
   "credits": ["<title> by <author>, <license> (<provider>) <source page>", ...]}
Candidate = the contract's {id, provider, kind, title, url, thumb, w, h, duration, license, attribution, source_page,
cost_usd}. Picking and fetching go through media.select (another team's package): `pick(brief) -> {"chosen",
"alternates", "notes"}` and `fetch(candidate) -> local path` (adapters below accept dicts, dataclasses or objects).
Without that package (or offline), cues stay "unresolved" and the compiler shows the text card they replaced.
A slot the creator already decided (swapped / rejected / approved) is never re-picked, so the same media.json always
renders the same reel. Paid candidates (cost_usd > 0) never spend here: approve() checks the per-reel cap ($5 by
default) and the global daily cap ($20, ledger file) and the next resolve generates it.
"""
import dataclasses
import datetime
import importlib
import json
import os
import re
from pathlib import Path

VERSION = 1
REEL_CAP, DAY_CAP = 5.0, 20.0
KEEP = {"swapped", "rejected", "approved"}          # the creator's decisions: never re-picked
SHOWN = {"picked", "swapped", "approved"}           # statuses whose chosen file renders
CUTOUT = {"parallax", "sticker"}                     # treatments that need the subject cut out of the image
N_ALT = 4


class MediaError(ValueError):
    pass


def media_path(out_dir) -> Path:
    """Where a build's media.json lives: the Studio project root (project.json) within two levels above the build's
    directory (so the build and the preview share the creator's picks), else next to the build (directed.json)."""
    base = Path(out_dir).resolve().parent
    for d in (base, base.parent, base.parent.parent):
        if (d / "project.json").is_file():
            return d / "media.json"
    return base / "media.json"


def load(path) -> dict:
    try:
        doc = json.loads(Path(path).read_text())
        return doc if isinstance(doc, dict) and isinstance(doc.get("items"), dict) else _empty()
    except (OSError, ValueError):
        return _empty()


def _empty() -> dict:
    return {"version": VERSION, "items": {}, "credits": []}


def save(path, doc: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["credits"] = credits(doc)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.part")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def slot_of(shot_id: str, c) -> str:
    return str(c.params.get("slot") or f"{shot_id}.{c.start_word}")


def media_cues(script) -> list[tuple[str, int, object]]:
    return [(slot_of(sh.id, c), si, c) for si, sh in enumerate(script.shots) for c in sh.cues
            if c.type == "broll" and c.params.get("kind") == "media"]


def brief(script, si: int, c) -> dict:
    """What the selector searches for: the cue's query and kind, providers in order, the insert's shape."""
    p, sh = c.params, script.shots[si]
    est = max(1.2, 0.35 * (c.end_word - c.start_word + 1))
    return {"slot": slot_of(sh.id, c), "query": p["query"], "kind": p.get("media", "image"),
            "providers": list(p.get("providers") or []), "treatment": p.get("treatment", "kenburns"),
            "layout": p.get("layout", "full"), "duration": [2.0, 10.0], "insert_s": round(est, 2),
            "orientation": "portrait" if p.get("layout") in ("split", "inset") else "any", "min_short_side": 1080,
            "allow_paid": False, "paid_ok": bool(p.get("paid_ok")), "title": script.title,
            "reel": script.title, "clip": slot_of(sh.id, c),           # the paid quote's ledger keys (media.budget)
            "at": " ".join(w.text for w in sh.words[c.start_word:c.end_word + 1])}


def cand(x) -> dict | None:
    """A Candidate as a plain dict (dataclass, object or dict in; None stays None)."""
    if x is None:
        return None
    if dataclasses.is_dataclass(x):
        d = dataclasses.asdict(x)
    elif isinstance(x, dict):
        d = dict(x)
    else:
        d = {k: getattr(x, k) for k in dir(x) if not k.startswith("_") and not callable(getattr(x, k))}
    for k in ("path", "file", "local"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = str(d[k])
    if not d.get("path") and (d.get("file") or d.get("local")):
        d["path"] = d.get("file") or d.get("local")
    d["cost_usd"] = float(d.get("cost_usd") or 0.0)
    return json.loads(json.dumps(d, default=str))


def _select_mod():
    try:
        return importlib.import_module("reel_director.media.select")
    except Exception:            # not written yet / import error inside it: resolution is simply off
        return None


def default_selector():
    """media.select's pick(brief) (or select / choose), normalised to {"chosen", "alternates", "notes"}; None when
    the package is missing."""
    m = _select_mod()
    fn = next((getattr(m, n) for n in ("pick", "select", "choose") if m and callable(getattr(m, n, None))), None)
    if fn is None:
        return None

    def run(b: dict) -> dict:
        res = fn(b)
        if isinstance(res, (list, tuple)) and not isinstance(res, dict):
            res = {"chosen": res[0] if res else None, "alternates": list(res[1:])}
        res = res if isinstance(res, dict) else {"chosen": res}
        return {"chosen": cand(res.get("chosen")), "alternates": [cand(a) for a in res.get("alternates") or []],
                "notes": [str(n) for n in res.get("notes") or []]}
    return run


def default_fetch(c: dict, approved: bool = False) -> str | None:
    """Local file for a candidate through media.select.fetch / media.fetch; a paid one only when approved."""
    if c.get("cost_usd", 0) > 0 and not approved:
        return None
    for mod in ("reel_director.media.select", "reel_director.media"):
        try:
            fn = getattr(importlib.import_module(mod), "fetch", None)
        except Exception:
            fn = None
        if callable(fn):
            out = fn(c, approved=True) if approved else fn(c)
            return str(getattr(out, "path", out)) if out else None
    return None


def _try_fetch(fetch, c: dict, approved: bool, notes: list) -> str | None:
    """fetch() that never sinks the build: a dead link or a refused paid fetch leaves the slot unresolved."""
    try:
        return fetch(c, approved=approved) if approved else fetch(c)
    except Exception as e:      # noqa: BLE001 - provider errors, ApprovalRequired, network
        notes.append(f"fetch {c.get('id')}: {type(e).__name__}: {str(e)[:160]}")
        return None


def _segment(path: str, need: float, notes: list) -> list[float] | None:
    """The clip window to show (media.select.clip_segment: scene cuts, no faces / text), else from the start."""
    m = _select_mod()
    fn = getattr(m, "clip_segment", None) if m else None
    try:
        return [round(float(x), 3) for x in fn(Path(path), need)] if fn else None
    except Exception as e:      # noqa: BLE001
        notes.append(f"segment {Path(path).name}: {e}")
        return None


def _local(c: dict | None) -> bool:
    return bool(c and c.get("path") and Path(c["path"]).is_file())


def _cutouts(item: dict, root: Path, notes: list) -> None:
    ch = item.get("chosen")
    if item.get("treatment") not in CUTOUT or not _local(ch) or item.get("media") != "image" or ch.get("cutout"):
        return
    from . import cutout
    try:
        info = cutout.make(Path(ch["path"]), root / "media" / f"{item['slot']}")
        ch.update(info)
    except Exception as e:      # a cutout is an upgrade: without it parallax uses a soft focus layer, sticker a card
        notes.append(f"media: {item['slot']}: no cutout ({e})")


def resolve(script, path, selector=None, fetch=default_fetch, offline: bool | None = None,
            notes: list | None = None) -> dict:
    """Pick + fetch every media cue that has no decision yet; write media.json. Returns the document."""
    notes = notes if notes is not None else []
    path = Path(path)
    doc = load(path)
    doc["title"] = script.title
    offline = offline if offline is not None else os.environ.get("RD_MEDIA_OFFLINE") == "1"
    sel = selector or (None if offline else default_selector())     # offline: no default (network) selector ...
    fetch = None if offline and fetch is default_fetch else fetch     # ... and no downloads (decided picks wait)
    live = set()
    for slot, si, c in media_cues(script):
        live.add(slot)
        b = brief(script, si, c)
        item = doc["items"].get(slot) or {}
        item.pop("stale", None)                      # a re-plan brought its cue back
        same = item.get("query") == b["query"] and item.get("media") == b["kind"]
        item.update({"slot": slot, "shot": script.shots[si].id, "at": b["at"], "query": b["query"], "media": b["kind"],
                     "providers": b["providers"], "treatment": item.get("treatment_set") or b["treatment"],
                     "layout": b["layout"], "paid_ok": b["paid_ok"]})
        doc["items"][slot] = item
        if same and item.get("status") in KEEP | {"picked"} and (_local(item.get("chosen")) or item["status"] == "rejected"):
            _cutouts(item, path.parent, notes)
            continue
        if same and item.get("status") in ("swapped", "approved") and item.get("chosen"):
            got = _try_fetch(fetch, item["chosen"], item["status"] == "approved", notes) if fetch else None
            if got:
                item["chosen"]["path"] = got
                _cutouts(item, path.parent, notes)
            else:
                notes.append(f"media: {slot}: {item['status']} pick not fetched yet (provider not available)")
            continue
        if sel is None:
            item.update(status="unresolved", chosen=None, alternates=item.get("alternates") or [],
                        notes=["offline" if offline else "media.select not installed: the text card shows"])
            continue
        try:
            res = sel(b)
        except Exception as e:          # one provider outage must not stop the build
            item.update(status="unresolved", chosen=None, notes=[f"select failed: {e}"])
            notes.append(f"media: {slot}: select failed ({e})")
            continue
        pool, ch = [a for a in [res.get("chosen")] + list(res.get("alternates") or []) if a], None
        for a in [a for a in pool if a.get("cost_usd", 0) <= 0][:3]:   # never spend without approval; a dead link
            if not _local(a) and fetch:                                  # falls through to the next free pick
                a["path"] = _try_fetch(fetch, a, False, res.setdefault("notes", []))
            if _local(a):
                ch = a
                break
        alts = [a for a in pool if a is not ch]
        if _local(ch) and b["kind"] == "video" and not ch.get("segment"):
            ch["segment"] = _segment(ch["path"], b["insert_s"], res["notes"])
        item.update(status="picked" if _local(ch) else "unresolved", chosen=ch if _local(ch) else None,
                    alternates=alts[:N_ALT * 2], notes=res.get("notes") or [])
        if any(a.get("cost_usd", 0) > 0 for a in alts) and not _local(ch):
            item["status"] = "awaiting_approval" if item.get("paid_ok") else "unresolved"
        _cutouts(item, path.parent, notes)
    for slot in list(doc["items"]):
        if slot not in live:
            doc["items"][slot]["status"] = doc["items"][slot].get("status", "picked")
            doc["items"][slot]["stale"] = True       # its cue left the plan; kept so a re-plan can find it again
    save(path, doc)
    n = sum(1 for s in live if doc["items"][s].get("status") in SHOWN)
    if live:
        notes.append(f"media: {n}/{len(live)} media insert(s) resolved -> {path}")
    return doc


def chosen(doc: dict | None, slot: str) -> dict | None:
    """The file a slot renders, or None (rejected, unresolved, paid not yet approved, file missing)."""
    item = (doc or {}).get("items", {}).get(slot)
    if not item or item.get("status") not in SHOWN or not _local(item.get("chosen")):
        return None
    return {**item["chosen"], "treatment": item.get("treatment_set") or item.get("treatment")}


def credits(doc: dict) -> list[str]:
    out = []
    for slot in sorted(doc.get("items", {})):
        it = doc["items"][slot]
        c = it.get("chosen") or {}
        if it.get("status") not in SHOWN or it.get("stale") or not c:
            continue
        line = c.get("attribution") or " by ".join(x for x in (c.get("title"), c.get("author")) if x) or c.get("id", slot)
        lic = c.get("license") or "license unknown"
        out.append(f"{line}, {lic} ({c.get('provider', '?')})" + (f" {c['source_page']}" if c.get("source_page") else ""))
    return list(dict.fromkeys(out))


def write_credits(build, timeline=None) -> list[str]:
    """<build>/renders/reel.credits.txt: the licences of the media the built reel shows (timeline.json "credits");
    removed when it shows none, so no stale credits sit beside a reel. CLI builds and Studio share it."""
    build = Path(build)
    try:
        tl = json.loads(Path(timeline or build / "reel" / "timeline.json").read_text())
        lines = [str(x) for x in tl.get("credits") or []]
    except (OSError, ValueError, AttributeError):
        lines = []
    f = build / "renders" / "reel.credits.txt"
    sa = sorted({m for x in lines for m in re.findall(r"CC BY-SA [\d.]+", x)})      # license.write_credits' notice
    if lines:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("B-roll credits\n" + "".join(f"- {x}\n" for x in lines) + (
            f"\nShare-alike: this reel adapts {', '.join(sa)} material; those inserts are shared under the same "
            "license.\n" if sa else ""))
    elif f.exists():
        f.unlink()
    return lines


def credits_text(doc: dict) -> str:
    lines = credits(doc)
    return ("B-roll credits\n" + "\n".join(f"- {x}" for x in lines) + "\n") if lines else ""


# ---- creator decisions (Studio) ------------------------------------------------------------------------------
def _item(doc: dict, slot: str) -> dict:
    item = doc.get("items", {}).get(slot)
    if not item:
        raise MediaError(f"no media slot {slot!r}")
    return item


def _alt(item: dict, alt_id: str) -> dict:
    pool = [item.get("chosen")] + list(item.get("alternates") or [])
    c = next((a for a in pool if a and str(a.get("id")) == str(alt_id)), None)
    if c is None:
        raise MediaError(f"slot {item['slot']!r} has no alternate {alt_id!r}")
    return c


def requery(path, slot: str, query: str, kind: str | None = None, pick: int = 1, selector=None, fetch=default_fetch,
            orientation: str = "any", min_short_side: int = 720) -> dict:
    """The creator's own search for a slot ("search for something else"): their words through the selector, the
    pick-th ranked free result (1 = best, after they looked at the list) becomes the pick, the rest stay alternates.
    A decision ("swapped"): the director's query is kept, so the next resolve never re-picks it. Free only."""
    doc = load(path)
    item = _item(doc, slot)
    sel = selector or default_selector()
    if sel is None:
        raise MediaError("media.select is not available")
    b = {"slot": slot, "query": query, "kind": kind or item.get("media") or "image", "providers": [],
         "duration": [2.0, 10.0], "orientation": orientation, "min_short_side": min_short_side, "paid_ok": False,
         "at": item.get("at", ""), "treatment": item.get("treatment"), "layout": item.get("layout")}
    try:
        res = sel(b)
    except Exception as e:      # noqa: BLE001 - a source outage is the creator's message, not a crash
        raise MediaError(f"search failed: {type(e).__name__}: {str(e)[:200]}") from e
    ranked = [a for a in [res.get("chosen")] + list(res.get("alternates") or []) if a and a.get("cost_usd", 0) <= 0]
    if not 1 <= pick <= len(ranked):
        raise MediaError(f"{len(ranked)} free result(s) for {query!r}: pick 1..{len(ranked)}" if ranked
                         else f"no allowed {b['kind']} for {query!r}")
    c, notes = ranked[pick - 1], list(res.get("notes") or [])
    if not _local(c) and fetch:
        c["path"] = _try_fetch(fetch, c, False, notes)
    if not _local(c):
        raise MediaError(f"{c.get('id')}: not downloaded ({'; '.join(notes[-1:])})")
    if c.get("kind") == "video" and not c.get("segment"):
        c["segment"] = _segment(c["path"], 3.0, notes)
    old = [a for a in [item.get("chosen")] + list(item.get("alternates") or []) if a]
    keep = {a.get("id") for a in ranked}
    item.update(chosen=c, status="swapped", query_set=query, notes=notes,
                alternates=([a for a in ranked if a is not c] + [a for a in old if a.get("id") not in keep])[:N_ALT * 2])
    _cutouts(item, Path(path).parent, notes)
    save(path, doc)
    return item


def swap(path, slot: str, alt_id: str, fetch=None) -> dict:
    """Use an alternate. Without `fetch` the download waits for the next build's resolve (the Studio's way)."""
    doc = load(path)
    item = _item(doc, slot)
    c = _alt(item, alt_id)
    if c.get("cost_usd", 0) > 0:
        raise MediaError(f"{alt_id!r} is a paid generation (${c['cost_usd']:.2f}): approve it instead")
    old = item.get("chosen")
    item["alternates"] = [a for a in item.get("alternates") or [] if a is not c] + ([old] if old and old is not c else [])
    if not _local(c) and fetch:
        c["path"] = _try_fetch(fetch, c, False, item.setdefault("notes", []))
    item.update(chosen=c, status="swapped")
    _cutouts(item, Path(path).parent, item.setdefault("notes", []))
    save(path, doc)
    return item


def reject(path, slot: str) -> dict:
    doc = load(path)
    item = _item(doc, slot)
    item["status"] = "rejected"
    save(path, doc)
    return item


def restore(path, slot: str) -> dict:
    doc = load(path)
    item = _item(doc, slot)
    item["status"] = "swapped" if _local(item.get("chosen")) else "unresolved"
    save(path, doc)
    return item


def set_treatment(path, slot: str, name: str) -> dict:
    from .broll_media import TREATMENTS
    if name not in TREATMENTS:
        raise MediaError(f"treatment must be one of {list(TREATMENTS)}")
    doc = load(path)
    item = _item(doc, slot)
    item["treatment_set"] = item["treatment"] = name
    _cutouts(item, Path(path).parent, item.setdefault("notes", []))
    save(path, doc)
    return item


def ledger_path() -> Path:
    return Path(os.environ.get("RD_MEDIA_LEDGER") or Path.home() / ".cache" / "reel-director" / "media-spend.json")


def _budget():
    """The paid-generation ledger (media.budget, shared with the Veo / Higgsfield clients), or None."""
    try:
        return importlib.import_module("reel_director.media.budget").Budget.from_settings()
    except Exception:            # noqa: BLE001 - not installed / unreadable settings: the local ledger guards
        return None


def _request_id(c: dict) -> str | None:
    rid = (c.get("extra") or {}).get("request_id") or c.get("request_id")
    return str(rid) if rid else None


def spend(doc: dict, today: str | None = None) -> dict:
    today = today or datetime.date.today().isoformat()
    try:
        led = json.loads(ledger_path().read_text())
    except (OSError, ValueError):
        led = {}
    reel = sum(float((it.get("approved") or {}).get("cost_usd", 0)) for it in doc.get("items", {}).values())
    out = {"reel_usd": round(reel, 2), "reel_cap_usd": float(doc.get("reel_cap_usd", REEL_CAP)),
           "day_usd": round(float(led.get(today, 0.0)), 2), "day_cap_usd": DAY_CAP, "date": today, "ledger": "local"}
    b = _budget() if any(_request_id((it.get("approved") or {})) for it in doc.get("items", {}).values()) else None
    if b is not None:            # paid quotes live in the shared ledger: its caps and today's spend are the truth
        try:
            s = b.summary()
            out.update(day_usd=round(float(s["spent_today_usd"]) + float(s["reserved_usd"]), 2),
                       day_cap_usd=float(s["daily_cap_usd"]), reel_cap_usd=float(s["per_reel_cap_usd"]),
                       ledger=s["ledger"])
        except Exception:        # noqa: BLE001 - an unreadable ledger never hides the local numbers
            pass
    return out


def approve(path, slot: str, alt_id: str, today: str | None = None) -> dict:
    """Approve one paid generation: it must be the reel's paid-eligible insert (<= 1 by default) and fit the per-reel
    and the daily caps. Records the approval (and reserves it in the ledger); nothing is generated here."""
    doc = load(path)
    item = _item(doc, slot)
    c = _alt(item, alt_id)
    cost = float(c.get("cost_usd", 0))
    if cost <= 0:
        raise MediaError(f"{alt_id!r} is free: swap to it instead")
    if not item.get("paid_ok"):
        raise MediaError(f"slot {slot!r} is not the reel's paid insert (<= 1 paid clip per reel by default)")
    s = spend(doc, today)
    if s["reel_usd"] + cost > s["reel_cap_usd"] + 1e-9:
        raise MediaError(f"over the per-reel cap: ${s['reel_usd']:.2f} + ${cost:.2f} > ${s['reel_cap_usd']:.2f}")
    if s["day_usd"] + cost > s["day_cap_usd"] + 1e-9:
        raise MediaError(f"over the daily cap: ${s['day_usd']:.2f} + ${cost:.2f} > ${s['day_cap_usd']:.2f}")
    rid, b = _request_id(c), None
    if rid and (b := _budget()) is not None:     # a real quote: the shared ledger approves it (its caps, fail-closed)
        try:
            b.approve(rid, by="studio")
        except Exception as e:      # noqa: BLE001 - BudgetExceeded / ApprovalRequired / LedgerError
            raise MediaError(f"not approved: {e}") from e
    else:                           # no quote ledger: reserve it in the local one
        led_p = ledger_path()
        try:
            led = json.loads(led_p.read_text())
        except (OSError, ValueError):
            led = {}
        led[s["date"]] = round(float(led.get(s["date"], 0.0)) + cost, 2)
        led_p.parent.mkdir(parents=True, exist_ok=True)
        led_p.write_text(json.dumps(led, indent=1, sort_keys=True))
    item.update(chosen=c, status="approved", approved={"id": c.get("id"), "provider": c.get("provider"),
                                                        "cost_usd": cost, "date": s["date"], "request_id": rid,
                                                        "ledger": "budget" if b is not None else "local"})
    save(path, doc)
    return item
