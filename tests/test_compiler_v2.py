"""Compiler v2: muted picture layers + transition windows, punches, B-roll, graphics, captions, and the
review fixes (z-order, overlay stacking, zoom pops, asset collisions, end clamping, number chunks)."""
import json
import re

import pytest

from reel_director import compiler, stage
from reel_director.compiler import caption_chunks, compile_project, js_round
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline

pytestmark = pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(),
                                reason="motion-pack not installed")
A = "Most creators waste three hours editing one reel."
B = "What if the edit was finished before you pressed record?"


def asr(line, t0=1.0, step=0.3):
    out, t = [], t0
    for w in line.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + step - 0.02, 3)})
        t += step
    return out


def build(tmp_path, cues_a=(), cues_b=(), style=None, width=1080, take_tail=2.0, **kw):
    data = {"shots": [{"id": "a", "line": A, "cues": list(cues_a)}, {"id": "b", "line": B, "cues": list(cues_b)}]}
    if style:
        data["style"] = style
    s = parse_script(data, base_dir=tmp_path)
    takes = {}
    for sid, line in (("a", A), ("b", B)):
        src = tmp_path / f"{sid}.mp4"
        src.write_bytes(b"")
        w = asr(line)
        takes[sid] = [Take(src, w, w[-1]["e"] + take_tail)]
    tl = build_timeline(s, takes)
    compiler.probe_size.cache_clear()
    orig = compiler.probe_size
    compiler.probe_size = lambda path: (width, width * 16 // 9)
    try:
        html = compile_project(tl, tmp_path / "out", **kw).read_text()
    finally:
        compiler.probe_size = orig
    plan = json.loads(re.search(r'id="rd-plan">(.*?)</script>', html, re.S).group(1))
    return tl, html, plan


def test_mix_keeps_voice_sfx_and_music_out_of_the_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "media_duration", lambda path: 0.2)
    (tmp_path / "mix.wav").write_bytes(b"RIFF")
    (tmp_path / "pop.wav").write_bytes(b"")
    _, html, _ = build(tmp_path, cues_a=[{"type": "sfx", "at": "waste", "src": "pop.wav"}],
                       cues_b=[{"type": "transition", "at": "What", "id": "whip"}], mix=tmp_path / "mix.wav")
    audios = re.findall(r"<audio [^>]*>", html)
    assert len(audios) == 1 and 'id="mix"' in audios[0] and 'src="assets/mix.wav"' in audios[0]
    videos = re.findall(r"<video [^>]*>", html)
    assert videos and all(" muted " in v and "data-has-audio" not in v for v in videos)


def test_without_mix_voice_plays_at_the_unstretched_edit(tmp_path):
    tl, html, plan = build(tmp_path, cues_b=[{"type": "transition", "at": "What", "id": "whip"}])
    w = plan["windows"][0]
    assert (w["key"], w["cutF"] - w["startF"], w["endF"] - w["cutF"]) == ("whip", 5, 4)   # 300 ms = 9 frames, JS round(4.5) = 5 before the cut
    b = tl.shots[1]
    v = re.search(r'<video id="take-b-0"[^>]*data-start="([\d.]+)"[^>]*data-media-start="([\d.]+)"', html)
    a = re.search(r'<audio id="vo-b-0"[^>]*data-start="([\d.]+)"[^>]*data-media-start="([\d.]+)"', html)
    assert float(v.group(1)) == pytest.approx(w["startF"] / 30, abs=1e-6)            # picture starts early
    assert float(a.group(1)) == pytest.approx(b.out_start)                            # voice does not
    assert float(v.group(1)) - float(v.group(2)) == pytest.approx(float(a.group(1)) - float(a.group(2)), abs=1e-5)
    prev = re.search(r'<video id="take-a-0"[^>]*data-start="([\d.]+)" data-duration="([\d.]+)"', html)
    assert float(prev.group(1)) + float(prev.group(2)) == pytest.approx(w["endF"] / 30, abs=1e-6)


def test_transition_clamps_to_media_headroom_or_falls_back_to_a_cut(tmp_path):
    _, _, plan = build(tmp_path, cues_b=[{"type": "transition", "at": "What", "id": "dip-to-black"}], take_tail=0.1)
    w = plan["windows"][0]
    assert w["endF"] - w["cutF"] <= js_round(0.1 * 30) + 1      # outgoing take has ~0.1 s + post-roll left
    _, _, plan = build(tmp_path, cues_b=[{"type": "transition", "at": "What", "id": "cut"}])
    assert plan["windows"] == []


def test_cards_and_graphics_paint_under_captions(tmp_path):
    _, html, _ = build(tmp_path, cues_a=[{"type": "cutaway", "at": "three", "until": "reel", "text": "3 HOURS"},
                                         {"type": "broll", "at": "waste", "kind": "stat", "value": "3", "label": "hours"},
                                         {"type": "overlay", "at": "one reel", "text": "ONE"}])
    caps = html.index('<div id="caps">')
    for m in re.finditer(r'class="clip (card|overlay)', html):
        assert m.start() < caps
    assert html.index('<div id="stage">') < html.index('class="clip card cutaway') < html.index('<div id="fx-vig"')


def test_overlay_ends_when_the_next_overlay_or_a_card_starts(tmp_path):
    tl, html, _ = build(tmp_path, cues_a=[{"type": "overlay", "at": "creators", "text": "ONE"},
                                          {"type": "overlay", "at": "three", "text": "TWO"},
                                          {"type": "broll", "at": "editing", "kind": "text", "text": "cut"}])
    ov = [(float(s), float(d)) for s, d in re.findall(r'class="clip overlay[^"]*" data-start="([\d.]+)" data-duration="([\d.]+)"', html)]
    p = tl.shots[0]
    assert ov[0][0] + ov[0][1] == pytest.approx(p.words[3].start)       # stops for the second chip
    assert ov[1][0] + ov[1][1] == pytest.approx(p.words[5].start)       # and the second stops for the B-roll card


def test_close_zooms_are_envelopes_inside_the_shot(tmp_path):
    tl, _, plan = build(tmp_path, cues_a=[{"type": "zoom", "at": "waste", "scale": 1.12},
                                          {"type": "zoom", "at": "hours", "scale": 1.2},
                                          {"type": "zoom", "at": "reel", "scale": 1.1}])
    zooms = plan["segs"][0]["zooms"]
    shot_end = tl.shots[0].out_start + tl.shots[0].duration
    for t0, t1, t2, t3, _ in zooms:
        assert t0 < t1 <= t2 < t3 <= shot_end + 1e-6

    def scale(t):                                     # the runtime's rule: max of the envelopes, never a restart
        z = 0.0
        for t0, t1, t2, t3, sc in zooms:
            if t0 <= t <= t3:
                x = (t - t0) / (t1 - t0) if t < t1 else 1 if t <= t2 else 1 - (t - t2) / (t3 - t2)
                x = min(1, max(0, x))
                z = max(z, (sc - 1) * x * x * (3 - 2 * x))
        return 1 + z
    steps = [abs(scale((f + 1) / 30) - scale(f / 30)) for f in range(int(shot_end * 30))]
    assert max(steps) < 0.045                         # one smooth 0.25 s ramp; the old fromTo restarts jumped ~0.1


def test_punch_ladder_is_on_the_word_frame_and_T_needs_a_wide_take(tmp_path):
    cues = [{"type": "punch", "at": "waste", "level": "M"}, {"type": "punch", "at": "reel", "level": "T"}]
    tl, _, plan = build(tmp_path, cues_a=cues, width=1080)
    p = tl.shots[0]
    # council Z3: a 1080-wide crop caps every level at 1.10 x 1080/1080 (T falls back to M first); the jitter
    # centres 0.02 under the cap, so capped punches still vary (1.06-1.10) instead of repeating 1.10
    got = plan["segs"][0]["punches"]
    assert [f for f, _ in got] == [js_round(p.words[2].start * 30), js_round(p.words[7].start * 30)]
    assert all(1.06 <= k <= 1.10 for _, k in got) and got[0][1] != got[1][1]
    _, _, plan = build(tmp_path, cues_a=cues, width=1440)
    m, t = plan["segs"][0]["punches"][0][1], plan["segs"][0]["punches"][1][1]
    assert 1.15 <= m <= 1.19 and 1.30 <= t <= 1.34      # ladder +- 0.02 jitter, seeded from crc32(title)
    _, _, again = build(tmp_path, cues_a=cues, width=1440)
    assert again["segs"][0]["punches"] == plan["segs"][0]["punches"]


def test_same_basename_assets_never_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "media_duration", lambda path: 0.2)
    for d in ("x", "y"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "hit.wav").write_bytes(d.encode())
    _, html, _ = build(tmp_path, cues_a=[{"type": "sfx", "at": "waste", "src": "x/hit.wav"},
                                         {"type": "sfx", "at": "hours", "src": "y/hit.wav"}])
    srcs = re.findall(r'<audio id="sfx-\d+" src="(assets/[^"]+)"', html)
    assert len(set(srcs)) == 2
    assert sorted((tmp_path / "out" / s).read_bytes() for s in srcs) == [b"x", b"y"]


def test_nothing_runs_past_the_root_duration(tmp_path):
    tl, html, plan = build(tmp_path, cues_b=[{"type": "zoom", "at": "record", "scale": 1.2},
                                             {"type": "overlay", "at": "record", "text": "END"},
                                             {"type": "lowerthird", "at": "record", "text": "Name"}], take_tail=0.0)
    D = tl.duration
    for s, d in re.findall(r'data-start="([\d.]+)" data-duration="([\d.]+)"', html):
        assert float(s) + float(d) <= D + 1e-6
    for seg in plan["segs"]:
        for z in seg["zooms"]:
            assert z[3] <= D + 1e-6


def test_caption_chunks_never_split_one_spoken_number():
    words = [{"w": w, "s": s, "e": e} for w, s, e in [("We", 0.15, 0.4), ("hit", 0.4, 0.65), ("three", 0.9, 1.6),
                                                       ("thousand", 0.9, 1.6), ("views", 1.6, 2.0), ("today.", 2.0, 2.5)]]
    chunks = caption_chunks(words, 3, 18)
    assert any(2 in c and 3 in c for c in chunks)
    assert caption_chunks([{"w": "a", "s": 0, "e": 1}, {"w": "b.", "s": 1, "e": 2}, {"w": "c", "s": 2, "e": 3}], 3, 18) == [[0, 1], [2]]


def test_cards_end_before_a_transition_out_of_their_shot(tmp_path):
    _, _, plan = build(tmp_path, cues_a=[{"type": "broll", "at": "one reel", "kind": "text", "text": "x", "layout": "split"}],
                       cues_b=[{"type": "transition", "at": "What", "id": "push"}])
    card = next(i for i in plan["items"] if i["kind"] == "broll")
    assert card["e"] <= plan["windows"][0]["startF"] / 30 + 1e-4


def test_every_graphic_kind_and_layout_is_emitted(tmp_path):
    (tmp_path / "c.mp4").write_bytes(b"")
    _, html, plan = build(tmp_path, style={"preset": "editorial"},
                          cues_a=[{"type": "title", "at": "Most", "text": "Stop wasting hours"},
                                  {"type": "broll", "at": "waste", "kind": "list", "items": ["a", "b"], "layout": "pip"},
                                  {"type": "broll", "at": "hours", "kind": "icon", "icon": "x", "text": "t", "layout": "split"},
                                  {"type": "callout", "at": "reel", "kind": "circle"}],   # captioned (no card over it)
                          cues_b=[{"type": "lowerthird", "at": "What", "text": "Ana", "sub": "Editor"},
                                  {"type": "endcard", "at": "record", "text": "Follow", "sub": "Save"}])
    kinds = {(i["kind"], i.get("layout")) for i in plan["items"]}
    assert {("title", None), ("broll", "pip"), ("broll", "split"), ("lowerthird", None), ("endcard", None)} <= kinds
    assert plan["callouts"][0]["kind"] == "circle" and 'id="co-0"' in html
    assert plan["caption"] == "minimal" and '"Instrument Serif"' in html and plan["grade"] == "warm"
    end = next(i for i in plan["items"] if i["kind"] == "endcard")
    assert end["e"] == pytest.approx(plan["D"]) and plan["D"] - end["s"] <= 1.6 + 1e-6
