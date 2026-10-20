"""v2 contract P1/P2: face-aware layout. Captions, title and stickers never cover the padded face; takes are
reframed toward an eye line of 0.40 H inside the resolution cap without showing an edge; punches scale about
the eye midpoint; reel/layout.json and the VISUALS hooks (data-kind / data-params / CSS vars / layers)."""
import json
import re
import subprocess

import pytest

from reel_director import compiler, layout, stage
from reel_director.compiler import compile_project
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline

pytestmark = pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(),
                                reason="motion-pack not installed")
A = "Most creators waste three hours editing one reel."
B = "What if the edit was finished before you pressed record?"


def asr(line, t0=1.0, step=0.3):
    return [{"w": w, "s": round(t0 + i * step, 3), "e": round(t0 + i * step + step - 0.02, 3)} for i, w in enumerate(line.split())]


def face_doc(name, dur, eye=0.53, fh=0.20, cx=0.53, W=1080, H=1920, step=3, fps=30):
    """A still face shaped like the founder's (real-1): box top 0.29 face h above the eye line, mouth 0.38 and
    chin 0.71 below it."""
    bh, ey = fh * H, eye * H
    bx, by = cx * W - bh / 2, ey - 0.29 * bh
    fr = {"box": [bx, by, bh, bh], "eyes": [[bx + 0.28 * bh, ey], [bx + 0.69 * bh, ey]],
          "mouth": [bx + 0.5 * bh, ey + 0.38 * bh], "chin_y": ey + 0.71 * bh, "conf": 1.0}
    n = round(dur * fps / step)
    return {"version": 1, "take": name, "w": W, "h": H, "fps": fps, "step": step,
            "frames": [{**fr, "t": round(i * step / fps, 4)} for i in range(n)],
            "summary": {"eye_y_med": eye, "face_h_med": fh, "center_x_med": cx, "present": 1.0, "stable": True}}


def build(tmp_path, cues_a=(), cues_b=(), faces=True, eye=0.53, fh=0.20, size=(1080, 1920), matte=False, out="out"):
    data = {"title": "Layout test", "shots": [{"id": "a", "line": A, "cues": list(cues_a)},
                                              {"id": "b", "line": B, "cues": list(cues_b)}]}
    s = parse_script(data, base_dir=tmp_path)
    (tmp_path / "prepped").mkdir(exist_ok=True)
    (tmp_path / "qa").mkdir(exist_ok=True)
    takes = {}
    for sid, line in (("a", A), ("b", B)):
        src = tmp_path / "prepped" / f"{sid}.mp4"
        src.write_bytes(b"")
        w = asr(line)
        dur = round(w[-1]["e"] + 2.0, 3)
        takes[sid] = [Take(src, w, dur)]
        if faces:
            doc = face_doc(sid, dur, eye, fh, W=size[0], H=size[1])
            (tmp_path / "qa" / f"{sid}.face.json").write_text(json.dumps(doc))
        if matte:
            (tmp_path / "prepped" / f"{sid}.matte.webm").write_bytes(b"")
    tl = build_timeline(s, takes)
    compiler.probe_size.cache_clear()
    orig = compiler.probe_size
    compiler.probe_size = lambda path: size
    try:
        html = compile_project(tl, tmp_path / out).read_text()
    finally:
        compiler.probe_size = orig
    plan = json.loads(re.search(r'id="rd-plan">(.*?)</script>', html, re.S).group(1))
    lay = json.loads((tmp_path / out / "layout.json").read_text())
    return tl, html, plan, lay


def xyxy(b):
    return [b[0], b[1], b[0] + b[2], b[1] + b[3]]


def no_text_on_faces(lay):
    """Every caption / title / sticker box against every visible face sample in its time span."""
    boxes = [(c["t0"], c["t1"], c["box"]) for c in lay["captions"]] + [(t["t0"], t["t1"], t["box"]) for t in lay["titles"]]
    boxes += [(c["t0"], c["t1"], c["box"]) for c in lay["cards"] if c["layout"] == "sticker"]
    for t0, t1, b in boxes:
        for f in lay["face_reel"]:
            if t0 <= f["t"] < t1 and not f.get("hidden"):
                assert layout._hit(xyxy(b), xyxy(f["box"])) == 0, (b, f)
    return True


def test_low_face_puts_captions_above_the_head_clear_of_face_and_title(tmp_path):
    _, html, _, lay = build(tmp_path, cues_a=[{"type": "title", "at": "Most", "until": "hours", "text": "3 HOURS PER REEL?"}])
    zones = {z["shot"]: z for z in lay["zones"]}
    assert zones["a"]["zone"] == zones["b"]["zone"] == "above-head"
    # one text block at a time (real-1 review): no caption shows while the hook title is up, so neither shot's
    # captions are pushed onto the hair: both clear it (HAIR x face h over the forehead) inside the safe rect
    for sid in "ab":
        hb = zones[sid]["box"]
        assert hb[1] + hb[3] <= zones[sid]["face"][1] - layout.HAIR * 0.20 * 1920 and hb[1] >= 288
    title = lay["title"]
    assert all(c["t0"] >= title["t1"] - 1e-6 or c["t1"] <= title["t0"] + 1e-6 for c in lay["captions"])
    assert no_text_on_faces(lay) and lay["overlaps"] == []
    cap = zones["a"]["box"]
    assert re.search(r'class="clip cap"[^>]*data-zone="above-head" style="left:172px;top:%dpx' % cap[1], html)


def test_well_framed_face_gets_captions_below_the_chin(tmp_path):
    _, _, _, lay = build(tmp_path, eye=0.36, fh=0.16)
    z = lay["zones"][0]
    assert z["zone"] == "below-chin" and z["box"][1] >= z["face"][1] + z["face"][3] and z["box"][1] + z["box"][3] <= 1248
    assert no_text_on_faces(lay)


def test_no_face_track_keeps_the_v1_band(tmp_path):
    tl, html, plan, lay = build(tmp_path, faces=False)
    assert {z["zone"] for z in lay["zones"]} == {"lower-band"} and lay["face_reel"] == [] and lay["overlaps"] == []
    assert 'style="left:' not in html and 'transform-origin:' not in html                    # v1 picture and band
    assert all("origin" not in s for s in plan["segs"])
    assert any("no face track" in n for n in plan["notes"])


def test_a_face_track_for_another_take_is_ignored(tmp_path):
    (tmp_path / "qa").mkdir()
    (tmp_path / "prepped").mkdir()
    (tmp_path / "qa" / "t.face.json").write_text(json.dumps(face_doc("t", 7.6)))
    doc, why = layout.load_face(tmp_path / "prepped" / "t.mp4", 6.5)
    assert doc is None and "7.60s track for a 6.50s take" in why
    doc, why = layout.load_face(tmp_path / "prepped" / "t.mp4", 7.6)
    assert doc and why is None


def test_punches_scale_about_the_eye_midpoint(tmp_path):
    _, html, plan, lay = build(tmp_path, cues_a=[{"type": "punch", "at": "waste", "level": "M"}])
    r, seg = lay["reframe"][0], plan["segs"][0]
    ex, ey = r["origin"]                                     # the pupils' midpoint, after the reframe
    assert ex == pytest.approx(r["scale"] * (0.53 * 1080 - 0.2 * 1920 / 2 + 0.485 * 0.2 * 1920) + r["tx"], abs=0.2)
    assert ey == pytest.approx(r["scale"] * 0.53 * 1920 + r["ty"], abs=0.2)
    assert f'id="F-a-0" style="transform-origin:{ex}px {ey}px"' in html
    if r["scale"] > 1.0:
        assert f'transform-origin:0 0;transform:translate({r["tx"]}px,{r["ty"]}px) scale({r["scale"]})' in html
    assert seg["punches"] and max(k for _, k in seg["punches"]) >= compiler.PUNCH_MIN_CAP   # >= 8 %: never a wobble


def test_reframe_stays_inside_the_cap_and_never_shows_an_edge(tmp_path):
    # 1080-wide: the cap (1.10) cannot reach 0.40 H from 0.53 H; punches keep their headroom
    _, _, plan, lay = build(tmp_path, cues_a=[{"type": "punch", "at": "waste", "level": "M"}])
    r = lay["reframe"][0]
    assert r["scale"] == pytest.approx(1.10 / layout.PUNCH_HEADROOM, abs=1e-4)
    assert r["eye_y_after"] <= r["eye_y_before"]
    assert len({(x["scale"], x["tx"], x["ty"]) for x in lay["reframe"]}) == 1   # one framing: no jump at the cut
    s, tx, ty = r["scale"], r["tx"], r["ty"]
    assert tx <= 0.01 and ty <= 0.01 and s * 1080 + tx >= 1079.99 and s * 1920 + ty >= 1919.99   # no edge shows
    assert max(k for _, k in plan["segs"][0]["punches"]) * s <= 1.10 + 1e-6       # reframe x punch <= the cap
    assert any("lower the camera" in n for n in plan["notes"])   # eyes low in frame: the camera comes down


def test_4k_take_reaches_the_eye_line(tmp_path):
    _, _, _, lay = build(tmp_path, size=(2160, 3840))
    for r in lay["reframe"]:
        assert 0.37 - 1e-6 <= r["eye_y_after"] <= 0.43 + 1e-6 and r["scale"] <= 2.2
        s, tx, ty = r["scale"], r["tx"], r["ty"]                # the cover-fit take spans exactly 1080 x 1920
        assert tx <= 0.01 and ty <= 0.01 and s * 1080 + tx >= 1079.99 and s * 1920 + ty >= 1919.99
    assert no_text_on_faces(lay)


def test_captions_move_to_the_card_band_only_at_a_card_cut(tmp_path):
    tl, html, plan, lay = build(tmp_path, cues_b=[{"type": "broll", "at": "edit was finished", "kind": "text", "text": "DONE"}])
    card = next(c for c in lay["cards"] if c["kind"] == "broll")
    assert card["layout"] == "full"
    for c in lay["captions"]:
        under = card["t0"] - 1e-3 <= c["t0"] and c["t1"] <= card["t1"] + 1e-3
        assert (c["zone"] == "card") == under and (not under or c["box"] == [172, 972, 696, 276])
    pieces = [c for c in plan["caps"] if re.match(r"cap-\d+p\d+$", c["id"])]
    for p in pieces:                                         # a continuation keeps its chunk's entrance time
        first = next(c for c in plan["caps"] if c["id"] == p["id"].rsplit("p", 1)[0])
        assert p["s"] == first["s"]
    assert no_text_on_faces(lay)


def test_visuals_hooks_on_cue_elements(tmp_path):
    _, html, plan, lay = build(tmp_path, cues_a=[{"type": "broll", "at": "waste", "kind": "stat", "value": "3",
                                                  "label": "hours", "layout": "split"},
                                                 {"type": "title", "at": "Most", "until": "hours", "text": "3 HOURS"}],
                               cues_b=[{"type": "overlay", "at": "finished", "text": "DONE"}], matte=True)
    card = re.search(r'<div id="broll-\d+" class="clip card broll split[^>]*>', html).group(0)
    prm = json.loads(re.search(r'data-params="([^"]*)"', card).group(1).replace("&quot;", '"'))
    assert 'data-kind="broll"' in card and prm["kind"] == "stat" and prm["value"] == "3"
    assert all(f"--f{k}:" in card for k in "xywh") and all(f"--{k}:" in card for k in "xywh")
    y, h = (int(re.search(rf"--{k}:(\d+)px", card).group(1)) for k in "yh")
    assert y + h <= 1056 - 24 - layout.CAP_H["bold"] - 24                  # content clears the captions over a split
    assert re.search(r'class="clip title"[^>]*data-kind="title" data-params=', html)
    assert re.search(r'class="clip overlay"[^>]*data-kind="overlay"[^>]*style="--x:70px;--y:\d+px', html)
    assert re.search(r'<div class="rf" data-layer="take"[^>]*><video id="take-a-0" class="clip take"[^>]*data-layer="background"', html)
    assert re.search(r'<video id="subj-a-0" class="clip take subject"[^>]*data-track-index="1[01]"[^>]*data-layer="subject"', html)
    assert "face_reel" in plan and plan["face_reel"] and all(len(f["box"]) == 4 for f in plan["face_reel"])
    assert no_text_on_faces(lay)


def test_layout_is_deterministic(tmp_path):
    runs = [build(tmp_path, cues_a=[{"type": "punch", "at": "waste", "level": "M"}], out=f"o{i}") for i in range(2)]
    assert runs[0][1] == runs[1][1]
    assert (tmp_path / "o0" / "layout.json").read_text() == (tmp_path / "o1" / "layout.json").read_text()


def test_busyness_tells_a_poster_from_a_bare_wall(tmp_path):
    busy, calm = tmp_path / "busy.mp4", tmp_path / "calm.mp4"
    for path, src in ((busy, "testsrc2=s=320x240:d=1"), (calm, "color=c=0xd8d4cc:s=320x240:d=1")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", str(path)], check=True)
    hi = layout.busyness(busy, 0.5, [0, 0, 320, 240], (320, 240))
    lo = layout.busyness(calm, 0.5, [0, 0, 320, 240], (320, 240))
    assert hi is not None and lo is not None and hi >= 0.6 > 0.35 > lo
    assert layout.busyness(tmp_path / "missing.mp4", 0.5, [0, 0, 320, 240], (320, 240)) is None
