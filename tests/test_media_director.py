"""v4 media B-roll: the director's media planning (recipes, rules, paid cap), the council pass, media.json resolution
and the Studio B-roll endpoints. No network: media.select is a stub; paid spends are only ledger records in tmp."""
import copy
import http.client
import json
import threading
from pathlib import Path

import pytest

from reel_director import broll_media as bm, director, lexicon as lx, mediaplan, pipeline, policy
from reel_director.schema import ScriptError, parse_script, script_to_dict
from reel_director.studio.project import Project
from reel_director.studio.runtime import Studio
from reel_director.studio.server import StudioServer
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
LINES = json.loads((ROOT / "examples" / "demo" / "script-lines-only.json").read_text())
LONG = {"title": "Long test reel", "shots": [
    {"id": "hook", "line": "I made $40,000 from one reel and nobody believed me."},
    {"id": "promise", "line": "Here's the exact system, step by step, so you can copy it."},
    {"id": "s1", "line": "First, write the script before you ever touch the camera."},
    {"id": "s2", "line": "Second, record five short takes, not one long take."},
    {"id": "s3", "line": "Third, cut every pause longer than half a second."},
    {"id": "turn", "line": "But here's the part nobody tells you: the hook is ninety percent of the work."},
    {"id": "proof", "line": "My best reel had a three second hook, and it got two million views in a week."},
    {"id": "payoff", "line": "So stop editing for hours and start writing better first lines."},
    {"id": "cta", "line": "Follow for the next breakdown on my laptop."}]}
PRESETS = ["bold-hustle", "clean-pro", "editorial", "tech-explainer", "beast-hype", "desi-bilingual"]


def run(data, preset, **style):
    d = copy.deepcopy(data)
    d["style"] = {**d.get("style", {}), "preset": preset, **style}
    s = parse_script(policy.prepare(d, preset))
    notes: list[str] = []
    out = pipeline.direct(s, None, notes=notes)
    return out, build_timeline(out), notes


def media(d):
    return [(si, sh, c) for si, sh in enumerate(d.shots) for c in sh.cues if c.type == "broll" and c.params.get("kind") == "media"]


# ---- recipes and the director ---------------------------------------------------------------------------------
def test_recipes_are_the_case_study_numbers_clamped_to_the_contract():
    want = {"retention-classic": ((0.05, 0.15), (1.2, 1.5)), "quiet-authority": ((0.0, 0.10), (2.0, 3.0)),
            "calm-premium": ((0.25, 0.40), (2.5, 3.0)), "motion-graphics-explainer": ((0.30, 0.40), (1.5, 3.0)),
            "story-hype": ((0.20, 0.35), (1.2, 2.5)), "desi-explainer": ((0.20, 0.30), (1.2, 2.5))}
    for preset, name in bm.PRESET_RECIPE.items():
        r = bm.recipe({"preset": preset})
        assert r["name"] == name and (r["share"], r["insert"]) == want[name]
        assert bm.INSERT[0] <= r["insert"][0] <= r["insert"][1] <= bm.INSERT[1] and r["share"][1] <= bm.SHARE_MAX
    assert bm.recipe({"preset": "clean-pro", "pace_profile": "calm-premium"})["name"] == "calm-premium"   # pack styles
    assert bm.recipe({"preset": "clean-pro", "media": False}) is None
    r = bm.recipe({"preset": "clean-pro", "media": {"share": [0.1, 0.9], "insert": [0.5, 9], "paid": 0}})
    assert r["share"] == (0.1, 0.40) and r["insert"] == (1.2, 3.0) and r["paid"] == 0


@pytest.mark.parametrize("preset", PRESETS)
def test_director_plans_media_cues_with_the_contract_fields(preset):
    d = copy.deepcopy(LONG)
    d["style"] = {"preset": preset}
    out = director.direct(parse_script(d))
    cues = media(out)
    assert cues, "no media insert planned"
    for si, sh, c in cues:
        p = c.params
        assert p["auto"] and p["why"].startswith("real-media B-roll")
        assert p["query"] and p["media"] in ("image", "video") and p["treatment"] in bm.TREATMENTS
        assert p["layout"] in ("full", "split", "pip", "inset") and p["slot"] == f"{sh.id}.{c.start_word}"
        assert p["providers"][0] == "library" and p["text"]                  # the creator's own media first
        assert (p["treatment"] in ("inset", "sticker")) == (p["layout"] == "inset") or p["treatment"] == "sticker"
        assert not (p["media"] == "video" and p["treatment"] in bm.IMAGE_ONLY)
        assert bool(set(p["providers"]) & set(bm.PAID)) == bool(p.get("paid_ok"))
        texts = [w.text for w in sh.words]
        assert not any(a <= c.end_word and c.start_word <= b for a, b in lx.number_phrases(texts))   # EP P6
    assert sum(1 for *_, c in cues if c.params.get("paid_ok")) <= 1
    treats = [c.params["treatment"] for *_, c in sorted(cues, key=lambda x: (x[0], x[2].start_word))]
    assert all(a != b for a, b in zip(treats, treats[1:]))                    # never the same look twice in a row


@pytest.mark.parametrize("preset", PRESETS)
def test_council_pass_keeps_media_inside_the_rules(preset):
    d, tl, notes = run(LONG, preset)
    P, r = policy._Pass(d, tl, []), bm.recipe(d.style)
    payoff = bm._payoff_t(P)
    off = 0.0
    for si, sh, c in media(d):
        a, b = P.span(si, c)
        assert bm.INSERT[0] - 1e-6 <= b - a <= min(bm.INSERT[1], r["insert"][1]) + 1e-6
        assert a >= bm.FIRST - 1e-6 and b <= payoff + 1e-6                   # after the title, never over the payoff
        if c.params["layout"] not in bm.FACE_KEPT:
            assert b <= tl.duration - bm.FACE_TAIL + 1e-6
            off += b - a
        assert c.params["background"] == policy.presets.DIRECTION[preset]["card"]
    assert off <= r["share"][1] * tl.duration + 1e-6
    assert sum(1 for *_, c in media(d) if c.params.get("paid_ok")) <= 1
    assert policy.metrics(d, tl)["broll_share"] <= bm.SHARE_MAX + 1e-6


def test_a_refused_media_insert_keeps_its_label_card():
    data = copy.deepcopy(LINES)
    data["shots"][1]["line"] = "What if your YouTube edit was finished before you even pressed record?"
    d, _, notes = run(data, "clean-pro")          # quiet-authority: face-off cap 10 % < a 2-3 s insert in 12 s
    cards = [c.params for sh in d.shots for c in sh.cues if c.type == "broll" and c.params.get("kind") == "text"]
    assert any("YouTube" in p["text"] for p in cards) and any("keeps its label card" in n for n in notes)


def test_media_off_and_manual_media_cues():
    d, _, _ = run(LONG, "editorial", media=False)
    assert not media(d)
    data = copy.deepcopy(LINES)
    data["shots"][1]["cues"] = [{"type": "broll", "at": "edit", "until": "finished", "kind": "media", "query": "my desk",
                                 "treatment": "inset", "layout": "inset", "src": "desk.jpg"}]
    d, _, _ = run(data, "bold-hustle")
    manual = [c for *_, c in media(d) if not c.params.get("auto")]
    assert len(manual) == 1 and manual[0].params["src"] == "desk.jpg" and manual[0].params["layout"] == "inset"


def test_media_cues_round_trip_and_inset_is_media_only():
    out = director.direct(parse_script({**copy.deepcopy(LONG), "style": {"preset": "editorial"}}))
    back = parse_script(script_to_dict(out))
    assert [c.params for *_, c in media(back)] == [c.params for *_, c in media(out)]
    bad = {"shots": [{"id": "a", "line": "One reel a day.", "cues": [
        {"type": "broll", "at": "reel", "kind": "text", "text": "REEL", "layout": "inset"}]}]}
    with pytest.raises(ScriptError, match="inset"):
        parse_script(bad)
    with pytest.raises(ScriptError, match="query"):
        parse_script({"shots": [{"id": "a", "line": "One reel a day.", "cues": [{"type": "broll", "at": "reel", "kind": "media"}]}]})


def test_media_planning_is_deterministic_and_idempotent():
    a, _, na = run(LONG, "beast-hype")
    b, _, nb = run(LONG, "beast-hype")
    assert script_to_dict(a) == script_to_dict(b) and na == nb
    once = director.direct(parse_script({**copy.deepcopy(LONG), "style": {"preset": "tech-explainer"}}))
    assert script_to_dict(director.direct(once)) == script_to_dict(once)


# ---- media.json resolution ------------------------------------------------------------------------------------
def cand(i, provider="openverse", cost=0.0, path=None, kind="image"):
    return {"id": f"c{i}", "provider": provider, "kind": kind, "title": f"Pick {i}", "url": f"https://x/{i}",
            "thumb": f"https://x/{i}.jpg", "w": 1920, "h": 1080, "duration": None, "license": "CC BY 4.0",
            "attribution": f"Pick {i} by Someone", "source_page": f"https://x/p/{i}", "cost_usd": cost,
            **({"path": str(path)} if path else {})}


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setenv("RD_MEDIA_LEDGER", str(tmp_path / "ledger.json"))
    img = tmp_path / "a.jpg"
    img.write_bytes(b"jpeg")
    d, _, _ = run(LONG, "editorial")
    calls = []

    def select(b):
        calls.append(b["slot"])
        return {"chosen": cand(0, path=img), "alternates": [cand(1), cand(2, "veo", 1.2, kind="video")], "notes": []}
    return d, tmp_path / "media.json", select, calls, img


def test_resolve_writes_picks_alternates_and_credits_once(plan):
    d, path, select, calls, img = plan
    fetched = []
    doc = mediaplan.resolve(d, path, selector=select, fetch=lambda c, approved=False: fetched.append(c["id"]) or str(img))
    slots = [mediaplan.slot_of(sh.id, c) for _, sh, c in media(d)]
    assert set(doc["items"]) == set(slots) and len(calls) == len(slots)
    it = doc["items"][slots[0]]
    assert it["status"] == "picked" and it["chosen"]["path"] == str(img) and len(it["alternates"]) == 2
    assert it["query"] and it["providers"] and it["treatment"]
    assert doc["credits"] == ["Pick 0 by Someone, CC BY 4.0 (openverse) https://x/p/0"]
    assert mediaplan.credits_text(doc).startswith("B-roll credits\n- Pick 0")
    mediaplan.resolve(d, path, selector=select)
    assert len(calls) == len(slots)                    # decided slots are never re-picked: same media.json, same reel
    assert json.loads(path.read_text())["items"][slots[0]]["chosen"]["id"] == "c0"


def test_a_paid_first_choice_is_never_taken_without_approval(tmp_path):
    d, _, _ = run(LONG, "editorial")
    slot, paid_slot = None, None
    for _, sh, c in media(d):
        if c.params.get("paid_ok"):
            paid_slot = mediaplan.slot_of(sh.id, c)
        slot = slot or mediaplan.slot_of(sh.id, c)
    doc = mediaplan.resolve(d, tmp_path / "m.json", selector=lambda b: {"chosen": cand(9, "veo", 0.8, kind="video")},
                            fetch=lambda c, approved=False: pytest.fail("fetched a paid candidate"))
    for s, it in doc["items"].items():
        assert it["chosen"] is None and it["alternates"][0]["provider"] == "veo"
        assert it["status"] == ("awaiting_approval" if s == paid_slot else "unresolved")


def test_offline_or_no_selector_leaves_label_cards(tmp_path):
    d, _, _ = run(LONG, "editorial")
    doc = mediaplan.resolve(d, tmp_path / "m.json", offline=True)
    assert doc["items"] and all(it["status"] == "unresolved" for it in doc["items"].values())
    assert all(mediaplan.chosen(doc, s) is None for s in doc["items"])


def test_swap_reject_restore_treatment(plan):
    d, path, select, _, img = plan
    mediaplan.resolve(d, path, selector=select, fetch=lambda c, approved=False: str(img))
    slot = next(iter(json.loads(path.read_text())["items"]))
    it = mediaplan.swap(path, slot, "c1", fetch=lambda c: str(img))
    assert it["status"] == "swapped" and it["chosen"]["id"] == "c1" and "c0" in [a["id"] for a in it["alternates"]]
    with pytest.raises(mediaplan.MediaError, match="paid"):
        mediaplan.swap(path, slot, "c2")
    assert mediaplan.reject(path, slot)["status"] == "rejected" and mediaplan.chosen(mediaplan.load(path), slot) is None
    assert mediaplan.restore(path, slot)["status"] == "swapped"
    assert mediaplan.set_treatment(path, slot, "polaroid")["treatment"] == "polaroid"
    assert mediaplan.chosen(mediaplan.load(path), slot)["treatment"] == "polaroid"
    with pytest.raises(mediaplan.MediaError):
        mediaplan.set_treatment(path, slot, "spin")


def test_paid_approval_caps(plan, tmp_path):
    d, path, select, _, img = plan
    mediaplan.resolve(d, path, selector=select, fetch=lambda c, approved=False: str(img))
    doc = mediaplan.load(path)
    paid = next(iter(doc["items"]))
    free = "x.1"
    doc["items"][free] = {**copy.deepcopy(doc["items"][paid]), "slot": free}
    doc["items"][paid]["paid_ok"], doc["items"][free]["paid_ok"] = True, False   # the director's <= 1 paid insert
    mediaplan.save(path, doc)
    with pytest.raises(mediaplan.MediaError, match="not the reel's paid insert"):
        mediaplan.approve(path, free, "c2")
    with pytest.raises(mediaplan.MediaError, match="free"):
        mediaplan.approve(path, paid, "c1")
    it = mediaplan.approve(path, paid, "c2", today="2026-10-20")
    assert it["status"] == "approved" and it["approved"]["cost_usd"] == 1.2
    assert json.loads((tmp_path / "ledger.json").read_text()) == {"2026-10-20": 1.2}
    doc = mediaplan.load(path)
    doc["items"][paid]["alternates"].append(cand(3, "veo", 4.5, kind="video"))
    mediaplan.save(path, doc)
    with pytest.raises(mediaplan.MediaError, match="per-reel cap"):          # 1.2 + 4.5 > $5
        mediaplan.approve(path, paid, "c3", today="2026-10-20")
    (tmp_path / "ledger.json").write_text(json.dumps({"2026-10-21": 19.5}))
    doc["items"][paid]["approved"] = None
    mediaplan.save(path, doc)
    with pytest.raises(mediaplan.MediaError, match="daily cap"):            # 19.5 + 1.2 > $20
        mediaplan.approve(path, paid, "c2", today="2026-10-21")


def test_a_quoted_paid_clip_is_approved_in_the_shared_budget_ledger(plan, tmp_path, monkeypatch):
    from reel_director.media.budget import Budget
    monkeypatch.setenv("REEL_DIRECTOR_PAID_LEDGER", str(tmp_path / "paid.jsonl"))
    d, path, select, _, img = plan
    mediaplan.resolve(d, path, selector=select, fetch=lambda c, approved=False: str(img))
    doc, b = mediaplan.load(path), Budget.from_settings()
    slot = next(iter(doc["items"]))
    rids = []
    for i, usd in ((5, 1.2), (6, 2.0)):          # two quotes (no money moves, no network)
        q = b.quote("veo", "veo-test", {"prompt": f"clock {i}"}, usd=usd, seconds=4, reel=d.title, clip=slot)
        rids.append(q.request_id)
        doc["items"][slot]["alternates"].append({**cand(i, "veo", usd, kind="video"), "extra": {"request_id": q.request_id}})
    doc["items"][slot]["paid_ok"] = True
    mediaplan.save(path, doc)
    it = mediaplan.approve(path, slot, "c5", today="2026-10-20")
    assert it["approved"]["ledger"] == "budget" and it["approved"]["request_id"] == rids[0]
    assert b.state(rids[0])["state"] == "approved" and not (tmp_path / "ledger.json").exists()   # one ledger
    assert mediaplan.spend(mediaplan.load(path))["ledger"].endswith("paid.jsonl")
    with pytest.raises(mediaplan.MediaError, match="not approved"):    # the ledger's own cap: 1 paid clip per reel
        mediaplan.approve(path, slot, "c6", today="2026-10-20")
    assert b.state(rids[1])["state"] == "quoted"


def test_media_path_shares_one_media_json_per_studio_project(tmp_path):
    (tmp_path / "project.json").write_text("{}")
    assert mediaplan.media_path(tmp_path / "reel") == tmp_path / "media.json"
    assert mediaplan.media_path(tmp_path / "preview" / "reel") == tmp_path / "media.json"
    assert mediaplan.media_path(tmp_path / "x" / "y" / "z" / "reel") == tmp_path / "x" / "y" / "z" / "media.json"


# ---- Studio B-roll endpoints -----------------------------------------------------------------------------------
@pytest.fixture
def studio(tmp_path, plan):
    d, _, select, _, img = plan
    sp = tmp_path / "script.json"
    sp.write_text(json.dumps(script_to_dict(d)))
    proj = Project(tmp_path / "proj", sp)
    mediaplan.resolve(d, proj.root / "media.json", selector=select, fetch=lambda c, approved=False: str(img))
    st = Studio(proj, normalize=lambda s, o: {}, check=lambda n: None)
    httpd = StudioServer(("127.0.0.1", 0), st)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    c.request(method, path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, json.loads(data) if (r.getheader("Content-Type") or "").startswith("application/json") else data


def test_studio_broll_panel_api(studio):
    st, v = call(studio, "GET", "/api/broll")
    assert st == 200 and v["items"] and v["spend"]["reel_cap_usd"] == 5.0 and v["spend"]["day_cap_usd"] == 20.0
    it = v["items"][0]
    assert it["chosen"]["license"] == "CC BY 4.0" and it["chosen"]["thumb"].startswith("https://")
    assert {a["id"] for a in it["alternates"]} == {"c1", "c2"} and v["credits"] and "kenburns" in v["treatments"]
    slot = it["slot"]
    st, body = call(studio, "POST", f"/api/broll/{slot}/swap?alt=c1")
    assert st == 200 and body["status"] == "swapped"
    assert call(studio, "POST", f"/api/broll/{slot}/approve?alt=c1")[0] == 400        # free: swap, not approve
    assert call(studio, "POST", f"/api/broll/{slot}/spin")[0] == 404
    assert call(studio, "POST", "/api/broll/..%2Fx/reject")[0] == 404
    st, f = call(studio, "GET", f"/api/broll/file?slot={slot}&i=1")                   # c0 is now an alternate (local)
    assert st == 200 and f == b"jpeg"
    assert call(studio, "GET", f"/api/broll/file?slot={slot}&i=9")[0] == 404
    studio.studio.build["state"] = "running"
    assert call(studio, "POST", f"/api/broll/{slot}/reject")[0] == 409
