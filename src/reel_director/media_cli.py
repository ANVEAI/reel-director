"""`python -m reel_director media ...`: the v4 B-roll engine in the terminal (the Studio B-roll panel's twin).

  media status                                  every source: available, kinds, paid, what to set up
  media search "<query>" [--kind image|video] [--providers a,b] [--orientation portrait|landscape|square|any]
               [--limit N] [--context "<spoken words>"] [--paid] [--json]
                                                ranked candidates, best first (nothing is downloaded)
  media pick <build dir | directed.json> [--media media.json] [--offline]
                                                plan-time resolution, the step `compile` runs: the directed reel's
                                                media inserts -> picks + alternates + credits in media.json
  media fetch <build | media.json> <slot> [--alt ID]   download a slot's pick (or a free alternate) into the cache
  media swap <build | media.json> <slot> <ID>          use a free alternate (downloads it now)
  media use <build | media.json> <slot> "<query>" [--kind image|video] [--pick N]
                                                       your own search for the slot: the N-th ranked free result
  media reject|restore <build | media.json> <slot>     show the text card instead / take the pick back
  media treatment <build | media.json> <slot> <name>   kenburns, parallax, sticker, device, polaroid, reveal, ...
  media credits <build | media.json> [--out FILE]      credit lines: the built reel's (timeline.json; also written to
                                                       <build>/renders/reel.credits.txt), else media.json's picks
Decisions take effect on the next compile (nothing is re-picked). A paid generation is never fetched here: approve it
in Studio or with `python -m reel_director.media.budget approve <request_id>`. YouTube CC downloads are opt-in
(media.youtube_download) and against YouTube's Terms of Service; the warning is printed whenever one is involved.
"""
import argparse
import json
import sys
from pathlib import Path

from . import mediaplan
from .studio.broll import YT_WARNING


def _media_json(target: str) -> Path:
    """media.json for a build dir (the one `compile` wrote), a directed.json, or the file itself."""
    t = Path(target)
    if t.is_dir():
        return t / "media.json" if (t / "media.json").exists() else mediaplan.media_path(t / "reel")
    return t if t.name != "directed.json" else mediaplan.media_path(t.parent / "reel")


def _settings(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text()) if path else None


def _cand_line(c: dict) -> str:
    size = f"{c.get('w')}x{c.get('h')}" if c.get("w") else "size ?"
    dur = f" {float(c['duration']):.1f}s" if c.get("duration") else ""
    cost = f"  ${float(c.get('cost_usd') or 0):.2f} PAID (needs approval)" if float(c.get("cost_usd") or 0) > 0 else ""
    return f"{c.get('id')}  {c.get('license') or '?'}  {size}{dur}  {str(c.get('title') or '')[:70]!r}{cost}"


def _warn_youtube(cands) -> None:
    if any((c or {}).get("provider") == "youtube_cc" for c in cands):
        print(f"warning: {YT_WARNING}", file=sys.stderr)


def show(doc: dict) -> None:
    items = doc.get("items") or {}
    if not items:
        print("  no media inserts in this plan")
    for slot in sorted(items):
        it = items[slot]
        if it.get("stale"):
            continue
        print(f"  {slot:<10} [{it.get('status')}] {it.get('treatment')}/{it.get('layout')}  "
              f"{it.get('query')!r} ({it.get('media')})  at {it.get('at')!r}")
        ch = it.get("chosen")
        if ch:
            print(f"      pick: {_cand_line(ch)}" + (f"\n            -> {ch['path']}" if ch.get("path") else ""))
        for k, a in enumerate(it.get("alternates") or [], 1):
            print(f"      alt {k}: {_cand_line(a)}")
        for n in it.get("notes") or []:
            print(f"      note: {n}")
        _warn_youtube([ch] + list(it.get("alternates") or []))
    for line in doc.get("credits") or []:
        print(f"  credit: {line}")


def cmd_status(a) -> int:
    from .media import providers as registry
    for r in registry.status(_settings(a.settings)):
        kinds = "/".join(r.get("kinds") or []) or "-"
        state = "ready" if r.get("available") else "off"
        paid = "  paid" if r.get("paid") else ""
        print(f"  {r['provider']:<12} {state:<5} {kinds:<11}{paid}" + (f"\n      setup: {r['setup']}" if r.get("setup")
                                                                       and not r.get("available") else ""))
        if r["provider"] == "youtube_cc":
            print(f"      note: {YT_WARNING}")
    return 0


def cmd_search(a) -> int:
    from .media import providers as registry
    from .media import select
    prefer = [p for p in (a.providers or "").split(",") if p]
    names = list(registry.FREE + registry.KEYED) + [n for n in prefer if n in registry.OTHER
                                                     and (a.paid or n not in registry.PAID)]
    provs = registry.build(names, settings=_settings(a.settings))
    o = None if a.orientation == "any" else a.orientation
    res = select.pick(a.query, a.kind, provs, prefer, None, a.min_short_side, (a.min_s, a.max_s), o,
                      alternates=a.limit, named={"context": a.context}).to_dict()
    ranked = [c for c in [res["chosen"]] + res["alternates"] if c]
    if a.json:
        print(json.dumps({"ranked": ranked, "notes": res["notes"]}, indent=1))
        return 0 if ranked else 1
    for n in res["notes"]:
        print(f"  note: {n}")
    for k, c in enumerate(ranked, 1):
        print(f"  {k}. {c.get('score', 0):.3f}  {_cand_line(c)}\n       {c.get('source_page') or c.get('url')}")
    _warn_youtube(ranked)
    if not ranked:
        print(f"no allowed {a.kind} for {a.query!r}")
    return 0 if ranked else 1


def cmd_pick(a) -> int:
    from .schema import load_script
    t = Path(a.target)
    directed = t / "directed.json" if t.is_dir() else t
    if not directed.is_file():
        raise SystemExit(f"error: no directed.json at {directed} (run compile or direct first)")
    d = load_script(directed)
    path = Path(a.media) if a.media else mediaplan.media_path(directed.parent / "reel")
    notes: list[str] = []
    doc = mediaplan.resolve(d, path, offline=True if a.offline else None, notes=notes)
    show(doc)
    for n in notes:
        print(f"  note: {n}")
    print(f"wrote {path}")
    return 0


def _slot(target: str, slot: str) -> tuple[Path, dict]:
    path = _media_json(target)
    item = mediaplan.load(path)["items"].get(slot)
    if not item:
        raise mediaplan.MediaError(f"no media slot {slot!r} in {path}")
    return path, item


def cmd_fetch(a) -> int:
    path, item = _slot(a.target, a.slot)
    c = mediaplan._alt(item, a.alt) if a.alt else item.get("chosen")
    if not c:
        raise mediaplan.MediaError(f"slot {a.slot!r} has no pick: name an alternate with --alt")
    if float(c.get("cost_usd") or 0) > 0:
        raise mediaplan.MediaError(f"{c['id']} is a paid generation (${c['cost_usd']:.2f}): approve it in Studio or "
                                   "with `python -m reel_director.media.budget approve <request_id>`; the next "
                                   "build generates it")
    _warn_youtube([c])
    try:
        got = mediaplan.default_fetch(c)
    except Exception as e:      # noqa: BLE001 - a dead link / provider error is a message, not a traceback
        raise mediaplan.MediaError(f"{c['id']}: {type(e).__name__}: {str(e)[:200]}") from e
    if not got:
        raise mediaplan.MediaError(f"{c['id']}: no file (provider not available)")
    print(got)
    return 0


def cmd_decide(a) -> int:
    path = _media_json(a.target)
    if a.cmd == "swap":
        _warn_youtube([mediaplan._alt(_slot(a.target, a.slot)[1], a.arg)])
        item = mediaplan.swap(path, a.slot, a.arg, fetch=mediaplan.default_fetch)
    elif a.cmd == "treatment":
        item = mediaplan.set_treatment(path, a.slot, a.arg)
    else:
        item = (mediaplan.reject if a.cmd == "reject" else mediaplan.restore)(path, a.slot)
    print(f"  {a.slot}: {item.get('status')}, {item.get('treatment')}: the next compile uses it ({path})")
    return 0


def cmd_use(a) -> int:
    item = mediaplan.requery(_media_json(a.target), a.slot, a.query, a.kind, a.pick)
    c = item["chosen"]
    _warn_youtube([c])
    print(f"  {a.slot}: now {_cand_line(c)}\n      -> {c['path']}\n  the next compile uses it; "
          f"{len(item.get('alternates') or [])} alternate(s) kept")
    return 0


def cmd_credits(a) -> int:
    t = Path(a.target)
    if t.is_dir() and (t / "reel" / "timeline.json").exists():
        lines = mediaplan.write_credits(t)          # also refreshes <build>/renders/reel.credits.txt
    else:
        lines = mediaplan.credits(mediaplan.load(_media_json(a.target)))
    text = ("B-roll credits\n" + "".join(f"- {x}\n" for x in lines)) if lines else ""
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text)
    print(text.rstrip() or "no third-party media: nothing to credit")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reel_director media", description="B-roll sources, picks and credits")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="which sources are live and what each needs")
    st.add_argument("--settings", help="settings JSON ({'media': {...}}); env vars win")
    s = sub.add_parser("search", help="ranked candidates for a query (no download)")
    s.add_argument("query")
    s.add_argument("--kind", default="image", choices=["image", "video"])
    s.add_argument("--providers", help="preferred sources first, comma separated (e.g. claude_clip,wikimedia)")
    s.add_argument("--orientation", default="portrait", choices=["portrait", "landscape", "square", "any"])
    s.add_argument("--min-short-side", type=int, default=1080)
    s.add_argument("--min-s", type=float, default=2.0, help="shortest usable clip, s")
    s.add_argument("--max-s", type=float, default=10.0)
    s.add_argument("--limit", type=int, default=6, help="alternates after the best")
    s.add_argument("--context", default="", help="the spoken words (Claude clips: brief context, gallery match)")
    s.add_argument("--paid", action="store_true", help="let preferred paid sources quote (never spends)")
    s.add_argument("--settings")
    s.add_argument("--json", action="store_true")
    p = sub.add_parser("pick", help="resolve a directed reel's media inserts -> media.json")
    p.add_argument("target", help="build dir (with directed.json) or a directed.json")
    p.add_argument("--media", help="media.json to write (default: the one compile uses)")
    p.add_argument("--offline", action="store_true", help="no network: unresolved inserts keep their text card")
    f = sub.add_parser("fetch", help="download a slot's pick or a free alternate into the media cache")
    f.add_argument("target")
    f.add_argument("slot")
    f.add_argument("--alt", help="alternate id (default: the slot's pick)")
    for name, arg in (("swap", "alternate id"), ("treatment", "treatment name"), ("reject", None), ("restore", None)):
        d = sub.add_parser(name, help=f"creator decision: {name}")
        d.add_argument("target")
        d.add_argument("slot")
        if arg:
            d.add_argument("arg", help=arg)
    u = sub.add_parser("use", help="creator decision: search with your own words and use the N-th result")
    u.add_argument("target")
    u.add_argument("slot")
    u.add_argument("query")
    u.add_argument("--kind", choices=["image", "video"], help="default: the slot's kind")
    u.add_argument("--pick", type=int, default=1, help="rank of the result to use (see `media search`), 1 = best")
    c = sub.add_parser("credits", help="credit lines of the built reel (or of media.json's picks)")
    c.add_argument("target")
    c.add_argument("--out")
    a = ap.parse_args(argv)
    cmds = {"status": cmd_status, "search": cmd_search, "pick": cmd_pick, "fetch": cmd_fetch, "credits": cmd_credits,
            "swap": cmd_decide, "treatment": cmd_decide, "reject": cmd_decide, "restore": cmd_decide, "use": cmd_use}
    try:
        return cmds[a.cmd](a)
    except mediaplan.MediaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
