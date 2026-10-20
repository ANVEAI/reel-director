"""v4 integration: plan-time media resolution in pipeline.build (media.json + credits before render), the `media` CLI,
claude_clip's gallery reuse while logged out, and the selector/registry seams between the teams. No network: the
selector is a stub, providers are fakes, the cache and work dirs live in tmp."""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reel_director import mediaplan, pipeline, policy
from reel_director.__main__ import main as cli
from reel_director.media import select
from reel_director.media import providers as registry
from reel_director.media.base import Candidate
from reel_director.media.cache import MediaCache
from reel_director.media.providers import claude_clip as cc
from reel_director.schema import parse_script

ROOT = Path(__file__).resolve().parents[1]
REEL = {"title": "Integration reel", "shots": [
    {"id": "hook", "line": "I made $40,000 from one reel and nobody believed me."},
    {"id": "s1", "line": "First, write the script before you ever touch the camera on your desk."},
    {"id": "s2", "line": "Then open your laptop and watch the editing timeline build itself."},
    {"id": "cta", "line": "Follow for the next breakdown on my laptop."}]}
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def still(path: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3366aa:s=640x400", "-frames:v", "1",
                    str(path)], check=True)
    return path


def script_file(tmp_path: Path, preset: str = "clean-pro") -> Path:
    d = copy.deepcopy(REEL)
    d["style"] = {"preset": preset}
    f = tmp_path / "script.json"
    f.write_text(json.dumps(d))
    return f


def stub(img: Path, calls: list):
    def select_(b):
        calls.append(b)
        return {"chosen": {"id": f"wikimedia:{b['slot']}", "provider": "wikimedia", "kind": "image", "url": "https://x",
                           "title": f"Pick for {b['query']}", "license": "cc-by-4.0", "path": str(img),
                           "attribution": f"Pick for {b['query']} by Someone, CC BY 4.0", "source_page": "https://p"},
                "alternates": [], "notes": ["stub"]}
    return select_


# ---- pipeline.build: resolution before compile, credits beside the reel ----------------------------------------
@needs_ffmpeg
def test_build_resolves_media_before_compile_and_writes_credits(tmp_path, monkeypatch):
    monkeypatch.setenv("RD_MEDIA_OFFLINE", "0")
    calls: list = []
    monkeypatch.setattr(mediaplan, "default_selector", lambda: stub(still(tmp_path / "pick.png"), calls))
    out = tmp_path / "b" / "reel"
    r = pipeline.build(script_file(tmp_path), out, None, "clean-pro", mix=False)
    doc = json.loads((tmp_path / "b" / "media.json").read_text())
    assert r["media"] == tmp_path / "b" / "media.json" and doc["items"] and len(calls) == len(doc["items"])
    assert all(it["status"] == "picked" for it in doc["items"].values())
    assert {b["reel"] for b in calls} == {"Integration reel"} and all(b["at"] and b["clip"] == b["slot"] for b in calls)
    tl = json.loads((out / "timeline.json").read_text())
    assert tl["credits"] and r["credits"] == tl["credits"] and "by Someone" in tl["credits"][0]
    assert (tmp_path / "b" / "renders" / "reel.credits.txt").read_text().startswith("B-roll credits\n- Pick for")
    first = (out / "index.html").read_text()
    pipeline.build(script_file(tmp_path), out, None, "clean-pro", mix=False)
    assert len(calls) == len(doc["items"])                      # decided: never re-picked
    assert (out / "index.html").read_text() == first            # same media.json, same reel


def test_offline_build_keeps_the_text_cards_and_writes_no_credits(tmp_path):
    out = tmp_path / "b" / "reel"
    r = pipeline.build(script_file(tmp_path), out, None, "clean-pro", mix=False)
    doc = json.loads((tmp_path / "b" / "media.json").read_text())
    assert doc["items"] and all(it["status"] == "unresolved" and it["notes"] == ["offline"]
                                for it in doc["items"].values())
    assert r["credits"] == [] and not (tmp_path / "b" / "renders" / "reel.credits.txt").exists()
    assert any("media: " in n for n in r["notes"])


def test_a_resolution_crash_never_sinks_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(mediaplan, "resolve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = pipeline.build(script_file(tmp_path), tmp_path / "b" / "reel", None, "clean-pro", mix=False)
    assert any("resolution failed (RuntimeError: boom)" in n for n in r["notes"]) and r["index"].exists()


def test_no_media_cues_and_no_media_json_means_no_file(tmp_path):
    f = script_file(tmp_path)
    d = json.loads(f.read_text())
    d["style"]["media"] = False
    f.write_text(json.dumps(d))
    r = pipeline.build(f, tmp_path / "b" / "reel", None, "clean-pro", mix=False)
    assert r["media"] is None and not (tmp_path / "b" / "media.json").exists()


# ---- resolve() semantics the integration relies on ---------------------------------------------------------------
def directed(preset="clean-pro"):
    d = copy.deepcopy(REEL)
    d["style"] = {"preset": preset}
    return pipeline.direct(parse_script(policy.prepare(d, preset)), None, notes=[])


def test_an_explicit_selector_runs_offline_but_default_fetch_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("RD_MEDIA_OFFLINE", "1")
    seen = []
    sel = lambda b: {"chosen": {"id": "a", "provider": "wikimedia", "url": "https://x", "license": "cc0"}}  # noqa: E731
    doc = mediaplan.resolve(directed(), tmp_path / "m.json", selector=lambda b: seen.append(b) or sel(b))
    assert seen and all(it["status"] == "unresolved" for it in doc["items"].values())   # offline: nothing downloaded


def test_a_dead_link_falls_through_to_the_next_free_alternate(tmp_path):
    img = tmp_path / "b.jpg"
    img.write_bytes(b"x")
    alts = [{"id": "dead", "provider": "wikimedia", "url": "https://dead"},
            {"id": "paid", "provider": "veo", "url": "veo://q", "cost_usd": 0.4},
            {"id": "ok", "provider": "nasa", "url": "https://ok"}]
    got = []

    def fetch(c, approved=False):
        got.append((c["id"], approved))
        if c["id"] == "dead":
            raise OSError("404")
        return str(img)
    doc = mediaplan.resolve(directed(), tmp_path / "m.json", selector=lambda b: {"chosen": alts[0], "alternates": alts[1:]},
                            fetch=fetch)
    it = next(iter(doc["items"].values()))
    assert it["status"] == "picked" and it["chosen"]["id"] == "ok" and ("paid", False) not in got
    assert [a["id"] for a in it["alternates"]] == ["dead", "paid"] and any("404" in n for n in it["notes"])


def test_a_cue_that_comes_back_is_no_longer_stale(tmp_path):
    d, path = directed(), tmp_path / "m.json"
    mediaplan.resolve(d, path, offline=True)
    doc = mediaplan.load(path)
    for it in doc["items"].values():
        it["stale"] = True
    mediaplan.save(path, doc)
    assert not any(it.get("stale") for it in mediaplan.resolve(d, path, offline=True)["items"].values())


# ---- seams between the teams --------------------------------------------------------------------------------------
class Src:
    def __init__(self, name, available=True, serves_cache=False):
        self.name, self.available, self.serves_cache, self.got = name, available, serves_cache, []


def test_order_keeps_a_logged_out_source_that_serves_its_cache():
    provs = {"wikimedia": Src("wikimedia"), "claude_clip": Src("claude_clip", False, True), "pixabay": Src("pixabay", False)}
    assert registry.order("video", provs, ["claude_clip"]) == ["claude_clip", "wikimedia"]


def test_named_args_reach_only_sources_that_name_them():
    class Plain:
        def search(self, query, kind="image", min_short_side=1080, limit=20):
            return [("plain", min_short_side, limit)]

    class Paid:
        def search(self, query, kind="video", limit=20, *, reel="", clip="", **spec):
            return [("paid", reel, clip, sorted(spec))]

    class Clip:
        def search(self, query, kind="video", limit=1, context=""):
            return [("clip", context, limit)]
    named = {"reel": "R", "clip": "turn.0", "context": "what if the edit"}
    assert select._search(Plain(), "q", "video", named, limit=5, orientation="portrait") == [("plain", 1080, 5)]
    assert select._search(Paid(), "q", "video", named, limit=5) == [("paid", "R", "turn.0", [])]
    assert select._search(Clip(), "q", "video", named, limit=5) == [("clip", "what if the edit", 5)]


def test_pick_with_a_brief_forwards_reel_clip_and_spoken_words(monkeypatch):
    seen = {}

    class Gen:
        name, available = "veo", True

        def search(self, query, kind="video", limit=20, *, reel="", clip="", **spec):
            seen.update(reel=reel, clip=clip)
            return [Candidate("veo:1", "veo", "video", query, "veo://quote/1", w=1080, h=1920, duration=4,
                              license="original", cost_usd=0.4)]

        def resolve(self, c):
            return c
    monkeypatch.setattr(registry, "build", lambda names, settings=None: {"veo": Gen()})
    res = select.pick({"query": "rocket", "kind": "video", "providers": ["veo"], "paid_ok": True, "reel": "R",
                       "clip": "turn.0", "at": "we launched"})
    assert seen == {"reel": "R", "clip": "turn.0"} and res["chosen"]["id"] == "veo:1"


# ---- claude_clip: accepted gallery clips serve while the CLI is logged out ---------------------------------------
def test_gallery_clips_are_offered_logged_out_by_shared_words(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    out = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps({"loggedIn": False}), "")  # noqa: E731
    cache = MediaCache(tmp_path / "cache")
    p = cc.ClaudeClipProvider(work_root=tmp_path / "work", cache=cache, pack=tmp_path, claude_bin="claude", run=out,
                              log=lambda s: None)
    made = [cc.ClipSpec("timeline auto-assembling with a checkmark", context="edit finished before you hit record"),
            cc.ClipSpec("clock racing through 3 hours of editing", context="3 hours editing"),
            cc.ClipSpec("timeline in a square", 1080, 1080, context="edit finished before you hit record")]
    for k, spec in enumerate(made):
        (tmp_path / "work" / spec.key()).mkdir(parents=True)
        (tmp_path / "work" / spec.key() / "spec.json").write_text(json.dumps(spec.as_dict()))
        f = tmp_path / f"{k}.mp4"
        f.write_bytes(b"mp4" + bytes([k]))
        cache.put(f, key=f"claude_clip:{spec.key()}", ext=".mp4", move=False)
    (tmp_path / "work" / "stale0000000000").mkdir()      # an older prompt version: its key no longer matches
    (tmp_path / "work" / "stale0000000000" / "spec.json").write_text(json.dumps(made[0].as_dict()))
    got = p.search("video editing timeline on a laptop screen", "video", limit=20,
                   context="What if the edit was finished before you")
    assert [c.id for c in got] == [f"claude_clip:{made[0].key()}"]          # 4 shared words; clock shares 1; square
    c = got[0]
    assert c.extra["reused"] and c.url.endswith(".mp4") and c.cost_usd == 0 and c.extra["description"].startswith("edit")
    assert Path(p.fetch(c.to_dict())).read_bytes() == b"mp4\x00"           # a cache hit: no `claude -p`
    assert p.search("rocket launching", "video", limit=20) == []             # nothing shared, nothing to make


# ---- the `media` CLI -----------------------------------------------------------------------------------------------
def build_dir(tmp_path: Path) -> Path:
    b = tmp_path / "b"
    (b / "reel").mkdir(parents=True)
    pipeline.write_directed(directed(), b / "directed.json")
    return b


def test_cli_pick_offline_writes_the_media_json_compile_uses(tmp_path, capsys):
    b = build_dir(tmp_path)
    assert cli(["media", "pick", str(b), "--offline"]) == 0
    doc = json.loads((b / "media.json").read_text())
    assert doc["items"] and f"wrote {b / 'media.json'}" in capsys.readouterr().out


def test_cli_decisions_fetch_and_credits(tmp_path, capsys):
    b = build_dir(tmp_path)
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    alts = [{"id": "free", "provider": "nasa", "license": "pd", "title": "Free", "path": str(img)},
            {"id": "veo:1", "provider": "veo", "cost_usd": 0.4, "url": "veo://quote/1"}]
    mediaplan.resolve(directed(), b / "media.json", selector=lambda b_: {
        "chosen": {"id": "c0", "provider": "wikimedia", "license": "cc-by-4.0", "path": str(img),
                   "attribution": "C0 by A, CC BY 4.0"}, "alternates": alts})
    slot = next(iter(mediaplan.load(b / "media.json")["items"]))
    assert cli(["media", "swap", str(b), slot, "free"]) == 0
    assert mediaplan.load(b / "media.json")["items"][slot]["chosen"]["id"] == "free"
    assert cli(["media", "swap", str(b), slot, "veo:1"]) == 2                  # paid: approve, never swap
    assert cli(["media", "fetch", str(b), slot, "--alt", "veo:1"]) == 2        # paid: never fetched here
    assert cli(["media", "fetch", str(b), slot]) == 0 and capsys.readouterr().out.strip().endswith(str(img))
    assert cli(["media", "reject", str(b), slot]) == 0
    assert mediaplan.load(b / "media.json")["items"][slot]["status"] == "rejected"
    assert cli(["media", "restore", str(b / "media.json"), slot]) == 0
    assert cli(["media", "credits", str(b / "media.json"), "--out", str(tmp_path / "c.txt")]) == 0
    assert "Free, pd (nasa)" in (tmp_path / "c.txt").read_text()
    (b / "reel" / "timeline.json").write_text(json.dumps({"credits": ["X by Y, CC BY 4.0 (wikimedia)"]}))
    assert cli(["media", "credits", str(b)]) == 0                              # a built reel: its timeline's lines
    assert (b / "renders" / "reel.credits.txt").read_text() == "B-roll credits\n- X by Y, CC BY 4.0 (wikimedia)\n"


def test_cli_search_ranks_without_downloading(monkeypatch, capsys):
    class Src_:
        name, available = "wikimedia", True

        def search(self, query, kind="image", limit=20, **kw):
            return [Candidate("wikimedia:1", "wikimedia", "image", "Clock tower at dusk", "https://x/1", w=2000,
                              h=3000, license="cc0-1.0", source_page="https://p/1"),
                    Candidate("wikimedia:2", "wikimedia", "image", "Bridge", "https://x/2", w=2000, h=3000,
                              license="cc-by-nc-4.0")]

        def resolve(self, c):
            return c
    monkeypatch.setattr(registry, "build", lambda names, settings=None: {"wikimedia": Src_()})
    assert cli(["media", "search", "clock tower", "--providers", "wikimedia"]) == 0
    out = capsys.readouterr().out
    assert "1. " in out and "wikimedia:1" in out and "wikimedia:2" not in out          # NC never offered


def test_requery_uses_the_creators_pick_and_resolve_keeps_it(tmp_path):
    img = tmp_path / "k.png"
    img.write_bytes(b"png")
    path, d = tmp_path / "m.json", directed()
    mediaplan.resolve(d, path, selector=lambda b: {"chosen": {"id": "clip", "provider": "claude_clip", "path": str(img),
                                                               "license": "original"}})
    slot = next(iter(mediaplan.load(path)["items"]))
    seen = []

    def sel(b):
        seen.append(b)
        return {"chosen": {"id": "a", "provider": "wikimedia", "url": "https://a", "license": "cc-by-sa-4.0"},
                "alternates": [{"id": "veo:1", "provider": "veo", "cost_usd": 0.4},
                               {"id": "b", "provider": "wikimedia", "url": "https://b", "license": "cc-by-sa-4.0",
                                "attribution": "Kdenlive by KDE, CC BY-SA 4.0"}]}
    with pytest.raises(mediaplan.MediaError, match="pick 1..2"):
        mediaplan.requery(path, slot, "kdenlive", "image", 3, selector=sel, fetch=lambda c: str(img))
    it = mediaplan.requery(path, slot, "kdenlive", "image", 2, selector=sel, fetch=lambda c: str(img))
    assert seen[-1]["query"] == "kdenlive" and seen[-1]["kind"] == "image" and not seen[-1]["paid_ok"]
    assert it["status"] == "swapped" and it["chosen"]["id"] == "b" and it["query_set"] == "kdenlive"
    assert [a["id"] for a in it["alternates"]] == ["a", "clip"]                # the earlier pick stays an alternate
    doc = mediaplan.resolve(d, path, selector=lambda b: pytest.fail("re-picked a creator decision"))
    assert doc["items"][slot]["chosen"]["id"] == "b" and doc["credits"][0].startswith("Kdenlive by KDE")


def test_credits_file_adds_the_share_alike_notice(tmp_path):
    (tmp_path / "reel").mkdir()
    (tmp_path / "reel" / "timeline.json").write_text(json.dumps({"credits": [
        '"Kdenlive" by A via Wikimedia Commons, CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)',
        "clock: AI-generated insert (Claude motion graphic), made for this reel"]}))
    assert len(mediaplan.write_credits(tmp_path)) == 2
    text = (tmp_path / "renders" / "reel.credits.txt").read_text()
    assert text.endswith("Share-alike: this reel adapts CC BY-SA 4.0 material; those inserts are shared under the "
                         "same license.\n")
