"""v4 media B-roll treatments: compiler emission per treatment and layout, faces sacred (insets clear of the face and
the captions), captions over real media, label-card fallback, colour match, cut-outs, determinism and the seek-safe
runtime (web/broll.mjs). Rendered proofs on the founder's takes live in work/v4-media (not unit tests)."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from reel_director import compiler, cutout, layout, mediaplan, stage, treatments
from reel_director.compiler import compile_project
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline

pytestmark = pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(),
                                reason="motion-pack not installed")
ROOT = Path(__file__).resolve().parents[1]
A = "Most creators waste three hours editing one reel."
B = "What if the edit was finished before you pressed record?"
MJS, CSS = (stage.WEB / "broll.mjs").read_text(), (stage.WEB / "reel.css").read_text()


def asr(line, t0=1.0, step=0.3):
    return [{"w": w, "s": round(t0 + i * step, 3), "e": round(t0 + i * step + step - 0.02, 3)} for i, w in enumerate(line.split())]


def face_doc(name, dur, eye=0.42, fh=0.16, cx=0.53, W=1080, H=1920, step=3, fps=30):
    bh, ey = fh * H, eye * H
    bx, by = cx * W - bh / 2, ey - 0.29 * bh
    fr = {"box": [bx, by, bh, bh], "eyes": [[bx + 0.28 * bh, ey], [bx + 0.69 * bh, ey]],
          "mouth": [bx + 0.5 * bh, ey + 0.38 * bh], "chin_y": ey + 0.71 * bh, "conf": 1.0}
    n = round(dur * fps / step)
    return {"version": 1, "take": name, "w": W, "h": H, "fps": fps, "step": step,
            "frames": [{**fr, "t": round(i * step / fps, 4)} for i in range(n)],
            "summary": {"eye_y_med": eye, "face_h_med": fh, "center_x_med": cx, "present": 1.0, "stable": True}}


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)   # noqa: E731
    run("-f", "lavfi", "-i", "testsrc2=s=640x480", "-frames:v", "1", str(d / "img.png"))
    run("-f", "lavfi", "-i", "testsrc2=s=540x960:d=2", "-pix_fmt", "yuv420p", str(d / "clip.mp4"))
    return d


def build(tmp_path, media, cue, out="out", faces=True, fh=0.16, eye=0.42, stub_cut=True, monkeypatch=None):
    data = {"title": "Media test", "style": {"preset": "clean-pro"},
            "shots": [{"id": "a", "line": A}, {"id": "b", "line": B, "cues": [cue] if cue else []}]}
    s = parse_script(data, base_dir=media)
    for sub in ("prepped", "qa"):
        (tmp_path / sub).mkdir(exist_ok=True)
    takes = {}
    for sid, line in (("a", A), ("b", B)):
        src = tmp_path / "prepped" / f"{sid}.mp4"
        src.write_bytes(b"")
        w = asr(line)
        dur = round(w[-1]["e"] + 2.0, 3)
        takes[sid] = [Take(src, w, dur)]
        if faces:
            (tmp_path / "qa" / f"{sid}.face.json").write_text(json.dumps(face_doc(sid, dur, eye, fh)))
    tl = build_timeline(s, takes)
    orig = compiler.probe_size
    compiler.probe_size = lambda path: (1080, 1920)
    try:
        html = compile_project(tl, tmp_path / out).read_text()
    finally:
        compiler.probe_size = orig
    plan = json.loads(re.search(r'id="rd-plan">(.*?)</script>', html, re.S).group(1))
    return html, plan, json.loads((tmp_path / out / "layout.json").read_text())


def mcue(treatment, layout="full", src="img.png", **kw):
    return {"type": "broll", "at": "edit", "until": "pressed", "kind": "media", "query": "video editing",
            "treatment": treatment, "layout": layout, "src": src, "text": "The edit", **kw}


@pytest.fixture(autouse=True)
def no_vision(monkeypatch):
    """Cut-outs in unit tests come from a fixed elliptical mask (Vision is exercised by the rendered proofs)."""
    real = cutout.make

    def make(image, stem, mask_fn=None):
        def mask(rgba):
            h, w = rgba.shape[:2]
            y, x = np.mgrid[:h, :w]
            return (((x - w / 2) / (w / 4)) ** 2 + ((y - h / 2) / (h / 3)) ** 2 <= 1).astype(np.uint8) * 255
        return real(image, stem, mask_fn or mask)
    monkeypatch.setattr(cutout, "make", make)


def xyxy(b):
    return [b[0], b[1], b[0] + b[2], b[1] + b[3]]


@pytest.mark.parametrize("treat,layout,src,dom", [
    ("fullbleed", "full", "clip.mp4", r'<video id="broll-\d+-m-src" class="clip m-src"[^>]*data-track-index="2"'),
    ("kenburns", "full", "img.png", r'class="m-layer"><img id="broll-\d+-m-src" class="m-src"'),
    ("parallax", "full", "img.png", r'class="m-src m-bg"[^>]*><img [^>]*class="m-src m-fg" src="assets/[^"]*cutout\.png"'),
    ("device", "full", "img.png", r'<div class="m-dev phone"><div class="m-lid"><div class="m-scr">'),
    ("polaroid", "split", "img.png", r'<div class="m-pola"><i class="m-back b1"></i>.*<figcaption></figcaption>'),   # split: captions only
    ("reveal", "full", "img.png", r'<div class="m-layer m-reveal">.*<div class="m-knock" style="--kn:\d+px;--ky:\d+px"><span>EDIT</span></div>'
                                  r'<div class="m-knock line" '),
    ("sticker", "full", "img.png", r'<div class="m-stk"><div class="m-stk-in"><img [^>]*class="m-src m-cut" src="assets/[^"]*sticker\.png"'),
    ("inset", "inset", "clip.mp4", r'class="clip minset t-inset"[^>]*><div id="broll-\d+-in" class="mi-box"><div class="m-inset-in"><video'),
])
def test_each_treatment_emits_its_dom_and_plan(tmp_path, media, treat, layout, src, dom):
    html, plan, lay = build(tmp_path, media, mcue(treat, layout, src, device="phone", mask="text"))
    assert re.search(dom, html, re.S), treat
    it = next(i for i in plan["items"] if i.get("media"))
    m = it["media"]
    assert it["bkind"] == "media" and m["t"] == treat and it["layout"] == layout
    assert m["video"] == src.endswith(".mp4") and len(m["kb"]) == 6 and set(m["match"]) == {"brightness", "saturate"}
    assert (tmp_path / "out" / "assets" / "rd" / "broll.mjs").read_text() == MJS
    assert lay["overlaps"] == []


def test_captions_paint_over_real_media_and_its_content_clears_them(tmp_path, media):
    html, plan, lay = build(tmp_path, media, mcue("device"))
    card = next(c for c in lay["cards"] if c["kind"] == "broll")
    under = [c for c in lay["captions"] if card["t0"] - 1e-3 <= c["t0"] < card["t1"]]
    assert under and all(c["zone"] == "card" and c["box"] == [172, 972, 696, 276] for c in under)   # the card band
    assert html.index('id="caps"') > html.index('id="stage"')             # #caps paints above #stage (B-roll)
    tag = re.search(r'<div id="broll-\d+" class="clip card broll full b-media t-device"[^>]*>', html).group(0)
    y, h = (int(re.search(rf"--{k}:(\d+)px", tag).group(1)) for k in "yh")
    assert y + h <= 972 - layout.GAP and " solo" not in tag


@pytest.mark.parametrize("treat,fill", [("device", True), ("polaroid", False), ("kenburns", True)])   # a laptop over
def test_split_objects_stay_whole_above_the_captions_and_pictures_fill_the_pane(tmp_path, media, treat, fill):  # split
    # captions would be ~50 % of the frame wide (v4 panel: unreadable): its screen fills the pane instead
    html, plan, lay = build(tmp_path, media, mcue(treat, "split", device="laptop"))
    tag = re.search(r'<div id="broll-\d+" class="clip card broll split b-media[^"]*"[^>]*>', html).group(0)
    y, h, pane = (int(re.search(rf"--{k}:(\d+)px", tag).group(1)) for k in ("y", "h", "split-h"))
    card = next(c for c in lay["cards"] if c["kind"] == "broll")
    cap_top = min(c["box"][1] for c in lay["captions"] if card["t0"] - 1e-3 <= c["t0"] < card["t1"])
    assert y + h == (pane if fill else cap_top) - layout.GAP and y == layout.MEDIA_TOP


def test_a_phone_too_small_for_the_split_pane_fills_it_instead(tmp_path, media):
    html, plan, _ = build(tmp_path, media, mcue("device", "split", device="phone"))
    it = next(i for i in plan["items"] if i.get("media"))
    assert it["media"]["t"] == "kenburns" and it["layout"] == "split" and 'class="m-dev phone"' not in html
    assert any("thumbnail-sized" in n for n in plan["notes"])


def test_unresolved_media_shows_its_label_card_and_hides_captions(tmp_path, media):
    cue = {**mcue("kenburns"), "src": None, "slot": "b.3"}
    cue.pop("src")
    html, plan, lay = build(tmp_path, media, cue)
    assert not any(i.get("media") for i in plan["items"])
    card = next(i for i in plan["items"] if i["kind"] == "broll")
    assert card["bkind"] == "text" and card["e"] - card["s"] <= treatments.FALLBACK_MAX + 1e-6
    assert not [c for c in lay["captions"] if card["s"] + 1e-3 < c["t0"] < card["e"] - 0.3]   # the card is the text
    assert 'class="card-text fit"><span class="tw">The</span> <span class="tw">edit</span>' in html


def test_a_media_json_pick_renders_and_a_rejection_falls_back(tmp_path, media):
    cue = {k: v for k, v in mcue("kenburns").items() if k != "src"}
    cue["slot"] = "b.3"
    doc = {"version": 1, "items": {"b.3": {"slot": "b.3", "status": "picked", "query": "video editing", "media": "image",
                                           "treatment": "polaroid", "chosen": {"id": "openverse:1", "provider": "openverse",
                                                                               "license": "cc-by-4.0", "path": str(media / "img.png")}}}}
    mediaplan.save(tmp_path / "media.json", doc)               # next to out/: the build's media.json
    _, plan, _ = build(tmp_path, media, cue)
    assert next(i for i in plan["items"] if i.get("media"))["media"]["t"] == "polaroid"   # the creator's treatment
    mediaplan.reject(tmp_path / "media.json", "b.3")
    _, plan, _ = build(tmp_path, media, cue, out="out2")
    assert not any(i.get("media") for i in plan["items"])


def test_inset_sits_clear_of_the_face_and_the_captions(tmp_path, media):
    html, plan, lay = build(tmp_path, media, mcue("inset", "inset", "clip.mp4"))
    ins = next(c for c in lay["cards"] if c["layout"] == "sticker" and c["kind"] == "broll")
    box = xyxy(ins["box"])
    assert ins["box"][2] * ins["box"][3] >= treatments.INSET_MIN
    for f in lay["face_reel"]:
        if ins["t0"] <= f["t"] < ins["t1"]:
            assert not f.get("hidden") and layout._hit(box, xyxy(f["head"])) == 0     # face kept and never covered
            hx, hy, hw, hh = f["head"]
            hair = [hx, hy - layout.HAIR * hh / (1 + layout.PAD + layout.CHIN_PAD), hx + hw, hy]
            assert layout._hit(box, hair) == 0                                        # nor the hair above it
    for c in lay["captions"]:
        if c["t0"] < ins["t1"] and ins["t0"] < c["t1"]:
            assert layout._hit(box, xyxy(c["box"])) == 0 and c["zone"] != "card"      # captions stay in their zone
    x0, y0, x1, y1 = treatments.STORY
    assert x0 <= box[0] and box[2] <= x1 and y0 <= box[1] and box[3] <= y1
    assert lay["overlaps"] == []


def test_inset_without_room_goes_split(tmp_path, media):
    _, plan, lay = build(tmp_path, media, mcue("inset", "inset", "img.png"), fh=0.34, eye=0.45)   # a huge face
    it = next(i for i in plan["items"] if i.get("media"))
    assert it["layout"] == "split" and any("split instead" in n for n in plan["notes"])


def test_a_short_clip_ends_the_insert_with_it(tmp_path, media):
    _, plan, _ = build(tmp_path, media, {**mcue("fullbleed", src="clip.mp4"), "until": "record?", "hold": 1.0})
    it = next(i for i in plan["items"] if i.get("media"))
    assert it["e"] - it["s"] <= treatments.duration(str(media / "clip.mp4")) + 1e-3


def test_credits_reach_the_timeline_and_the_studio_renders_folder(tmp_path, media):
    from reel_director.studio.broll import Broll
    build(tmp_path, media, mcue("kenburns", attribution="Desk by Jo, CC BY 4.0 (openverse)"), out="reel")
    tl = json.loads((tmp_path / "reel" / "timeline.json").read_text())
    assert tl["credits"] == ["Desk by Jo, CC BY 4.0 (openverse)"]
    proj = type("P", (), {"root": tmp_path})()
    assert Broll(proj).write_credits() == tl["credits"]
    assert (tmp_path / "renders" / "reel.credits.txt").read_text() == "B-roll credits\n- Desk by Jo, CC BY 4.0 (openverse)\n"
    build(tmp_path, media, mcue("kenburns"), out="reel")              # the creator's own file: nothing to credit
    assert json.loads((tmp_path / "reel" / "timeline.json").read_text())["credits"] == []
    assert Broll(proj).write_credits() == [] and not (tmp_path / "renders" / "reel.credits.txt").exists()


def test_compile_is_deterministic(tmp_path, media):
    a = build(tmp_path, media, mcue("parallax"), out="o1")[0]
    b = build(tmp_path, media, mcue("parallax"), out="o2")[0]
    assert a == b


def test_the_reveal_word_sits_on_the_brightest_band_of_the_picture(tmp_path):
    img = tmp_path / "band.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=1080x1920", "-vf",
                    "drawbox=y=400:h=320:w=1080:color=white:t=fill", "-frames:v", "1", str(img)], check=True)
    assert abs(treatments.bright_band(str(img), 0.0, 300) - 400) <= 16
    assert treatments.bright_band(str(tmp_path / "missing.png"), 0.0, 300) == 380      # unknown: the default


def test_colour_match_is_gentle_and_clamped():
    assert treatments.match((0.5, 0.2), (0.5, 0.2)) == {"brightness": 1.0, "saturate": 1.0}
    assert treatments.match((0.1, 0.4), (0.6, 0.05)) == {"brightness": 1.15, "saturate": 0.8}     # clamped
    assert treatments.match((0.4, 0.1), (0.5, 0.12))["brightness"] == pytest.approx((0.5 / 0.4) ** 0.5, abs=1e-3)
    assert treatments.match(None, (0.5, 0.1)) == {"brightness": 1.0, "saturate": 1.0}


def test_cutout_writes_a_subject_and_an_outlined_sticker(tmp_path, media):
    info = cutout.make(media / "img.png", tmp_path / "cut" / "s")
    cut = cutout.decode(Path(info["cutout"]))
    st = cutout.decode(Path(info["sticker"]))
    assert cut.shape[:2] == (480, 640) and 0.1 < (cut[..., 3] > 127).mean() < 0.4
    assert info["origin"] == pytest.approx([50, 50], abs=1) and info["aspect"] == pytest.approx(st.shape[1] / st.shape[0], abs=1e-3)
    ring = (st[..., 3] > 127) & (st[..., :3].min(axis=2) > 250)       # the white outline round the subject
    assert ring.any()
    again = cutout.make(media / "img.png", tmp_path / "cut" / "s")
    assert again == info                                               # cached, same answer
    with pytest.raises(cutout.CutoutError):
        cutout.make(media / "img.png", tmp_path / "cut" / "e", mask_fn=lambda rgba: np.zeros(rgba.shape[:2], np.uint8))


def test_runtime_is_seek_safe_and_loaded_only_for_media():
    code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", MJS, flags=re.S))
    for bad in ("Math.random", "Date.", "new Date", "performance.now", "requestAnimationFrame", "setTimeout", "setInterval"):
        assert bad not in code, bad
    reel = (stage.WEB / "reel.mjs").read_text()
    assert "media.length ? (await import('./broll.mjs')).prepare(" in reel and "drawMedia(it, t)" in reel
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert "animation" not in css and "transition:" not in css
    assert ".card.b-media.m-full .card-in { left: 0; top: 0; width: 100%; height: 100%;" in CSS
    assert re.search(r"\.minset \{[^}]*z-index: 3", CSS)              # over the take, under #caps (outside #stage)


def test_touched_files_stay_under_500_lines():
    src = ROOT / "src" / "reel_director"
    files = ["compiler.py", "layout.py", "director.py", "policy.py", "lexicon.py", "capplan.py", "schema.py",
             "broll_media.py", "mediaplan.py", "treatments.py", "cutout.py", "web/reel.mjs", "web/broll.mjs",
             "web/reel.css", "studio/server.py", "studio/runtime.py", "studio/broll.py", "studio/static/broll.js",
             "studio/static/studio.js", "studio/static/api.js", "studio/static/index.html"]
    for f in files:
        assert len((src / f).read_text().splitlines()) < 500, f


# ---- v4 final round: device size, payoff on the line, bridged hold, the device never leaves its box -------------
@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("fclips")
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)   # noqa: E731
    run("-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3:r=30", "-vf",
        "drawbox=x=300:y=700:w=480:h=480:color=white:t=fill:enable='gte(t,1.6)'", "-pix_fmt", "yuv420p", str(d / "event.mp4"))
    run("-f", "lavfi", "-i", "color=c=navy:s=1080x1920:d=1.0:r=30", "-pix_fmt", "yuv420p", str(d / "short.mp4"))
    return d


def test_a_full_layout_laptop_is_at_least_85_percent_of_the_frame(tmp_path, media):
    html, plan, lay = build(tmp_path, media, mcue("device", "full", device="laptop"))
    tag = re.search(r'<div id="broll-\d+" class="clip card broll full b-media t-device"[^>]*>', html).group(0)
    x, w, h = (int(re.search(rf"--{k}:(\d+)px", tag).group(1)) for k in "xwh")
    assert treatments.device_width("laptop", w, h) >= treatments.DEVICE_MIN * 1080 and x + w <= 1080 - 54
    card = next(c for c in lay["cards"] if c["kind"] == "broll")
    assert card["media"] == "device" and card["obj"][1] + card["obj"][3] <= 972 - layout.GAP     # above the captions


def test_the_clips_payoff_lands_on_the_lines_result_word(tmp_path, clips):
    html, plan, lay = build(tmp_path, clips, mcue("fullbleed", "split", src="event.mp4"))
    it = next(i for i in plan["items"] if i.get("media"))
    tl = json.loads((tmp_path / "out" / "timeline.json").read_text())
    hit = next(w["s"] for sh in tl["shots"] for w in sh["words"] if w["w"].strip(".,?") == "finished")
    start = float(re.search(r'<video id="broll-\d+-m-src"[^>]*data-media-start="([\d.]+)"', html).group(1))
    assert start + (hit - it["s"]) == pytest.approx(1.6, abs=1 / 30 + 1e-3)        # the square appears on "finished"
    assert it["media"]["pos"].endswith("%") and it["media"]["org"].endswith("px")


def test_a_bridged_insert_holds_its_clip_to_the_cut(tmp_path, clips):
    cue = {**mcue("fullbleed", "split", src="short.mp4"), "at": "before", "until": "record?", "to_cut": True,
           "hold": 2.0, "bridge": True, "beat": 8}
    html, plan, lay = build(tmp_path, clips, cue)
    it = next(i for i in plan["items"] if i.get("media"))
    tl = json.loads((tmp_path / "out" / "timeline.json").read_text())
    end = tl["shots"][-1]["start"] + tl["shots"][-1]["duration"]
    v = re.search(r'<video id="broll-\d+-m-src"[^>]*>', html).group(0)
    assert it["e"] == pytest.approx(end, abs=2e-3) and it["media"]["hold"] == pytest.approx(1.0, abs=0.04)
    assert 'data-media-start="0"' in v and re.search(r'src="assets/short-[\d.]+-[\d.]+-[\d.]+\.mp4"', v)
    assert float(re.search(r'data-duration="([\d.]+)"', v).group(1)) == pytest.approx(it["e"] - it["s"], abs=1e-3)
    assert 0 < it["media"]["beat"] < it["e"] - it["s"]


def test_the_device_lifts_about_its_base_and_never_drops_below_its_box():
    dev = re.search(r"function device\(.*?\n}\n", MJS, re.S).group(0)
    assert "translateY" not in dev and "rotateX" in dev and "scale(" in dev
    assert re.search(r"\.m-dev \{[^}]*transform-origin: 50% 100%", CSS)
    assert "url(#rd-tint)" in MJS and "m.pos" in MJS and "m.beat" in MJS
