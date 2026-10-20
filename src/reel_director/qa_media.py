"""QA gates for B-roll and real media (v4 final round; split out of qa.py, which re-exports them).

broll_face   B-roll on screen counts every layout (full, split, pip, a media inset: the v4 panel found split inserts
             reported as 0 %); the face-off share (full cards, the face hidden) keeps the pace cap; face presence and
             the longest no-face run as before; plus the framing gate (eye line, reachable by the 1.10 reframe).
media_share  real-media inserts (plan items carrying media) as a share of the runtime: contract v4 25-40 % (warn
             outside; a reel without real media is fine).
media_text   no caption or title box may touch a media OBJECT (device, polaroid, sticker, inset) while both are on
             screen (layout.json card "obj", the object's whole box incl. its animation): the v4 laptop rose through
             "WHAT IF THE". A picture that fills the pane is a background: captions over it are by design.
"""
import statistics

MEDIA_SHARE = (0.25, 0.40)


def _union(spans: list[tuple[float, float]]) -> float:
    tot, cur = 0.0, None
    for a, e in sorted(spans):
        if cur and a <= cur[1]:
            cur[1] = max(cur[1], e)
            continue
        tot += (cur[1] - cur[0]) if cur else 0.0
        cur = [a, e]
    return tot + ((cur[1] - cur[0]) if cur else 0.0)


def broll_spans(b: dict) -> list[tuple[float, float]]:
    """Every B-roll window on screen: cards of any layout plus media insets (layout.json 'sticker' broll cards)."""
    return [(c["t0"], c["t1"]) for c in b["layout"].get("cards", [])
            if c.get("kind") in ("broll", "cutaway") and (c.get("layout") != "sticker" or c.get("media"))]


def gate_broll_face(b: dict, ts, faces) -> list[dict]:
    from . import qa as Q
    D, cards = float(b["plan"]["D"]), Q.full_cards(b)
    cap = Q.PACE.get(b["style"].get("pace", "standard"), Q.PACE["standard"])[2]
    off = sum(e - a for a, e in cards) / D if D else 0.0
    share = _union(broll_spans(b) + cards) / D if D else 0.0
    hidden = [any(a <= t < e for a, e in cards) or f is None for t, f in zip(ts, faces)]
    vis = [f for t, f, h in zip(ts, faces, hidden) if not any(a <= t < e for a, e in cards)]
    present = sum(f is not None for f in vis) / len(vis) if vis else 0.0
    run = best = 0.0
    for k in range(1, len(ts)):
        run = run + ts[k] - ts[k - 1] if hidden[k] and hidden[k - 1] else 0.0
        best = max(best, run)
    lvl = "fail" if best > 6.0 or present < 0.6 else "warn" if off > cap + 1e-6 or present < 0.9 else "ok"
    g1 = Q._gate("broll_face", lvl, {"broll_share": round(share, 3), "faceoff_share": round(off, 3),
                                     "face_kept_share": round(max(0.0, share - off), 3), "face_present": round(present, 3),
                                     "longest_no_face_s": round(best, 2)},
                 f"face-off B-roll <= {cap:.0%}, face >= 90%, no-face <= 6 s",
                 f"B-roll {share:.0%} of the reel (face-off {off:.0%}, face kept {max(0.0, share - off):.0%}), face on "
                 f"{present:.0%} of face shots, longest no-face {best:.1f}s")
    out, bad, moved = {}, [], Q.relocated(b)
    before = {r["shot"]: r["eye_y_before"] for r in b["layout"].get("reframe", []) if r.get("eye_y_before")}
    for t, f in zip(ts, faces):
        if f is not None and not f.get("borrowed") and not any(a <= t < e for a, e in moved):
            out.setdefault(Q.shot_at(b, t), []).append(f)
    for sh, fs in out.items():
        eye = statistics.median((f["eyes"][0][1] + f["eyes"][1][1]) / 2 for f in fs) / Q.H
        sc, reach = Q.reframe_eye(before.get(sh, eye))   # reach from the take's own eye line, not the reframed one
        out[sh] = {"eye_y": round(eye, 3), "face_h": round(statistics.median(f["box"][3] for f in fs) / Q.H, 3),
                   "center_x": round(statistics.median(f["box"][0] + f["box"][2] / 2 for f in fs) / Q.W, 3),
                   "reframe_scale": sc, "reachable_eye_y": round(reach, 3)}
        if abs(eye - Q.EYE_TARGET) > Q.EYE_TOL:
            bad.append(sh)
    short = [k for k in bad if abs(out[k]["reachable_eye_y"] - Q.EYE_TARGET) > Q.EYE_TOL]
    scale = max((out[k]["reframe_scale"] for k in bad), default=1.0)
    reach_s = ", ".join(f"{out[k]['reachable_eye_y']:.2f}" for k in short)
    fixable = [k for k in bad if k not in short]          # the edit could reach 0.40 +- 0.03 and did not
    g2 = Q._gate("framing", "fail" if fixable else "warn" if bad else "ok", out,     # unreachable: a capture issue
                 f"eye line {Q.EYE_TARGET} H +- {Q.EYE_TOL}",
                 ("eye line " + ", ".join(f"{k} {v['eye_y']:.2f} H" for k, v in out.items()) if out else "no face to measure")
                 + (f"; the 1.10 reframe only reaches {reach_s} H for {', '.join(short)}: "
                    "lower or tilt the camera down for the rest (Studio coach)" if short else ""),
                 {"op": "reframe", "args": {"shots": fixable, "eye_y": Q.EYE_TARGET, "scale": scale}} if fixable else None)
    return [g1, g2]


def gate_media_share(b: dict) -> dict:
    from . import qa as Q
    D = float(b["plan"]["D"])
    items = [it for it in b["plan"].get("items", []) if it.get("media")]
    share = _union([(it["s"], it["e"]) for it in items]) / D if D else 0.0
    lo, hi = MEDIA_SHARE
    val = {"media_share": round(share, 3), "inserts": len(items),
           "layouts": sorted({str(it.get("layout")) for it in items})}
    tgt = f"real-media B-roll {lo:.0%}-{hi:.0%} of the runtime (contract v4)"
    if not items:
        return Q._gate("media_share", "ok", val, tgt, "no real-media inserts in this reel")
    msg = f"real-media B-roll {share:.0%} of the reel in {len(items)} insert(s)"
    if share < lo - 1e-6 or share > hi + 1e-6:
        return Q._gate("media_share", "warn", val, tgt, msg + (" (under " if share < lo else " (over ") +
                       f"{lo if share < lo else hi:.0%})")
    return Q._gate("media_share", "ok", val, tgt, msg)


def gate_media_text(b: dict) -> dict:
    from . import qa as Q
    from .layout_geo import _hit
    L = b["layout"]
    objs = [c for c in L.get("cards", []) if c.get("obj")]
    texts = [(c["t0"], c["t1"], c["box"], c.get("chunk_id", "caption"), c.get("text", "")) for c in L.get("captions", [])]
    ti = L.get("title")
    if ti and ti.get("box"):
        texts.append((ti["t0"], ti["t1"], ti["box"], "title", ti.get("text", "")))
    xyxy = lambda r: [r[0], r[1], r[0] + r[2], r[1] + r[3]]   # noqa: E731
    hits = [{"card": o["id"], "media": o.get("media"), "text": tid, "words": words,
             "t": round(max(o["t0"], t0), 2), "px2": round(_hit(xyxy(o["obj"]), xyxy(box)))}
            for o in objs for t0, t1, box, tid, words in texts
            if t0 < o["t1"] - 1e-6 and o["t0"] < t1 - 1e-6 and _hit(xyxy(o["obj"]), xyxy(box)) > 0]
    val = {"objects": len(objs), "overlaps": hits}
    if not hits:
        return Q._gate("media_text", "ok", val, "0 overlaps",
                       f"no caption or title touches a media object ({len(objs)} object insert(s))")
    w = hits[0]
    return Q._gate("media_text", "fail", val, "0 overlaps",
                   f"{len(hits)} text box(es) touch a media object; first {w['text']} '{w['words']}' on {w['card']} "
                   f"({w['media']}) at {w['t']:.2f}s")
