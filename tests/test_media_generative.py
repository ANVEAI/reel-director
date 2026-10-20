"""v4 media: paid generators (Veo on Vertex AI, Higgsfield API) and the budget / approvals ledger.

No network and no gcloud: HTTP is a scripted fake whose answers are shaped like the real responses recorded on
2026-10-20 (Vertex publisher-model list, testIamPermissions, predictLongRunning / fetchPredictOperation; Higgsfield
OpenAPI RequestStatus + /estimate). The core property under test: no paid request leaves without an approved quote
inside the caps, and one approval can never pay twice."""
import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from reel_director.media import budget as B
from reel_director.media import license as L
from reel_director.media.base import ApprovalRequired as BaseApprovalRequired
from reel_director.media.cache import MediaCache
from reel_director.media.providers import higgsfield as H
from reel_director.media.providers import veo as V

T0 = 1_792_500_000.0                                   # fixed wall clock (UTC day 2026-10-20)
DAY = lambda ts: time.strftime("%Y-%m-%d", time.gmtime(ts))  # noqa: E731
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"fake-veo-clip" * 50
OP = ("projects/demo-project/locations/us-central1/publishers/google/models/veo-3.1-fast-generate-001/"
      "operations/6f1c2d3e-0000-4000-8000-000000000001")
HF_ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"


class Clock:
    def __init__(self, t=T0):
        self.t, self.sleeps = t, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeHttp:
    """routes: {(METHOD, url substring): [responses...]} popped in order; every call is recorded."""

    def __init__(self, routes=None):
        self.routes, self.calls = {k: list(v) for k, v in (routes or {}).items()}, []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls.append(SimpleNamespace(method=method, url=url, headers=dict(headers or {}), body=body))
        for (m, part), answers in self.routes.items():
            if m == method and part in url:
                return answers.pop(0) if len(answers) > 1 else answers[0]
        raise AssertionError(f"unexpected {method} {url}")

    def hits(self, part):
        return [c for c in self.calls if part in c.url]


def gcloud(*a, **k):
    return SimpleNamespace(returncode=0, stdout="ya29.test-token\n", stderr="")


def budget(tmp_path, clock=None, **kw):
    return B.Budget(tmp_path / "paid-ledger.jsonl", clock=clock or Clock(), day=DAY, **kw)


def veo(tmp_path, http=None, bud=None, mono=None, **kw):
    mono = mono or Clock(0.0)
    kw.setdefault("run", gcloud)
    kw.setdefault("project", "demo-project")
    return V.VeoProvider(budget=bud or budget(tmp_path), cache=MediaCache(tmp_path / "cache"), http=http or FakeHttp(),
                         sleep=mono.sleep, clock=mono, **kw)


def done(videos=None, **resp):
    return 200, {"name": OP, "done": True, "response": {
        "@type": "type.googleapis.com/cloud.ai.large_models.vision.GenerateVideoResponse",
        "raiMediaFilteredCount": 0, "videos": videos if videos is not None else [
            {"bytesBase64Encoded": base64.b64encode(VIDEO).decode(), "mimeType": "video/mp4"}], **resp}}


# ---- Veo: price, request, quote ----------------------------------------------------------------------------------
def test_veo_price_of_a_4s_1080x1920_clip():
    assert V.frame_for(1080, 1920) == ("9:16", "1080p", 1080, 1920)
    assert V.frame_for(1080, 1080)[:2] == ("9:16", "1080p") and V.frame_for(1920, 1080)[0] == "16:9"
    assert V.frame_for(720, 1280)[1] == "720p"
    fast = V.estimate("veo-3.1-fast-generate-001", 4, "1080p", audio=False)
    assert (fast["usd_per_second"], fast["usd"], fast["samples"]) == (0.10, 0.40, 1)
    assert V.estimate("veo-3.1-fast-generate-001", 4, "1080p", audio=True)["usd"] == 0.48
    assert V.estimate("veo-3.1-generate-001", 4, "1080p")["usd"] == 0.80
    assert V.estimate("veo-3.1-generate-001", 4, "1080p", audio=True)["usd"] == 1.60
    assert V.estimate("veo-3.1-generate-001", 8, "4k")["usd"] == 3.20
    assert V.estimate("veo-3.1-fast-generate-001", 4, "720p")["usd"] == 0.32
    assert "C7E2-9256-1C43" in fast["basis"] and "D679-F281-7C1A" in fast["sku"]
    with pytest.raises(V.VeoError, match="no Vertex AI billing SKU"):
        V.estimate("veo-3.1-lite-generate-001", 4)
    with pytest.raises(V.VeoError, match="does not offer 4k"):
        V.estimate("veo-3.1-fast-generate-001", 8, "4k")             # Vertex: Veo 3.1 Fast is 720p / 1080p only
    for gone in ("veo-2.0-generate-001", "veo-3.0-generate-001", "veo-3.0-fast-generate-001"):
        with pytest.raises(V.VeoError, match="catalog"):
            V.estimate(gone, 4)
    with pytest.raises(V.VeoError, match="second clips"):
        V.estimate("veo-3.1-fast-generate-001", 5)
    assert [V.snap_seconds("veo-3.1-fast-generate-001", s) for s in (1.2, 4, 4.5, 7, 12)] == [4, 4, 6, 8, 8]


def test_veo_text_to_video_request_is_exact_and_deterministic():
    spec = V.make_spec("rocket launching at dawn, wide shot", seconds=2.5)
    seed = int(hashlib.sha256(b"veo-3.1-fast-generate-001|rocket launching at dawn, wide shot").hexdigest()[:8], 16)
    assert V.build_request(spec) == {"instances": [{"prompt": "rocket launching at dawn, wide shot"}], "parameters": {
        "aspectRatio": "9:16", "durationSeconds": 4, "sampleCount": 1, "personGeneration": "dont_allow",
        "seed": seed, "negativePrompt": V.DEFAULT_NEGATIVE, "resolution": "1080p", "generateAudio": False}}
    assert V.make_spec("rocket launching at dawn, wide shot", seconds=2.5) == spec
    land = V.build_request(V.make_spec("x", seconds=6, w=1280, h=720, audio=True))["parameters"]
    assert (land["aspectRatio"], land["resolution"], land["durationSeconds"], land["generateAudio"]) == \
        ("16:9", "720p", 6, True)
    gcs = V.build_request(V.make_spec("x", storage_uri="gs://bkt/out/"))["parameters"]
    assert gcs["storageUri"] == "gs://bkt/out/"


def test_veo_image_to_video_carries_the_quoted_image_only(tmp_path):
    img = tmp_path / "frame.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    spec = V.make_spec("slow push-in", image=img)
    inst = V.build_request(spec)["instances"][0]
    assert inst["image"] == {"bytesBase64Encoded": base64.b64encode(img.read_bytes()).decode(), "mimeType": "image/png"}
    img.write_bytes(b"\x89PNG\r\n\x1a\nswapped after approval")
    with pytest.raises(V.VeoError, match="changed since"):
        V.build_request(spec)


def test_veo_search_quotes_and_touches_no_network(tmp_path):
    http = FakeHttp()
    p = veo(tmp_path, http=http, run=lambda *a, **k: pytest.fail("search must not call gcloud"))
    [c] = p.search("money stack growing", kind="video", reel="reel-1", clip="shot-3")
    assert (c.provider, c.kind, c.w, c.h, c.duration, c.cost_usd) == ("veo", "video", 1080, 1920, 4.0, 0.40)
    assert c.license == "original" and L.allowed(c.license) and c.extra["ai_generated"] and c.extra["paid"]
    assert c.extra["approve"].endswith(c.extra["request_id"]) and c.id == f"veo:{c.extra['request_id']}"
    assert c.url == f"veo://quote/{c.extra['request_id']}"           # non-network marker: select.pick keeps it
    assert http.calls == [] and p.search("money", kind="image") == []
    assert [e["event"] for e in p.budget.events()] == ["quote"]
    assert p.search("money stack growing", reel="reel-1", clip="shot-3")[0].id == c.id   # idempotent quote
    assert p.search("money stack growing", "video", 1080, (2, 10), "portrait", 5, reel="reel-1",
                    clip="shot-3")[0].id == c.id                  # base-interface positional call with limit
    assert len(p.budget.events()) == 1 and p.resolve(c) is c


def test_veo_fetch_without_approval_spends_nothing(tmp_path):
    http = FakeHttp()
    p = veo(tmp_path, http=http)
    [c] = p.search("clock ticking fast", reel="r", clip="a")
    with pytest.raises(B.ApprovalRequired) as e:
        p.fetch(c)
    assert isinstance(e.value, BaseApprovalRequired)          # the resolver's generic except catches it
    assert http.calls == [] and [ev["event"] for ev in p.budget.events()] == ["quote"]


def test_veo_approved_clip_generates_once_and_is_cached(tmp_path):
    http = FakeHttp({("POST", ":predictLongRunning"): [(200, {"name": OP})],
                     ("POST", ":fetchPredictOperation"): [(200, {"name": OP}), done()]})
    mono = Clock(0.0)
    p = veo(tmp_path, http=http, mono=mono)
    [c] = p.search("rocket launching", reel="r", clip="a")
    p.budget.approve(c.extra["request_id"], by="founder")
    path = p.fetch(c)
    assert path.read_bytes() == VIDEO and path.suffix == ".mp4"
    side = json.loads(path.with_suffix(".json").read_text())
    assert side["ai_generated"] and side["license"] == "original" and side["cost_usd"] == 0.40
    [sub] = http.hits(":predictLongRunning")
    assert sub.body == V.build_request(p.budget.get(c.extra["request_id"]).spec)
    assert sub.url.startswith("https://us-central1-aiplatform.googleapis.com/v1/projects/demo-project/locations/"
                              "us-central1/publishers/google/models/veo-3.1-fast-generate-001")
    assert sub.headers == {"Authorization": "Bearer ya29.test-token", "x-goog-user-project": "demo-project"}
    assert [h.body for h in http.hits(":fetchPredictOperation")] == [{"operationName": OP}] * 2
    assert mono.sleeps == [5.0]
    st = p.budget.state(c.extra["request_id"])
    assert (st["state"], st["outcome"], st["charged"], st["operation"]) == ("settled", "completed", True, OP)
    assert p.budget.summary()["spent_today_usd"] == 0.40
    n = len(http.calls)
    assert p.fetch(c) == path and len(http.calls) == n          # cache hit: no second generation


def test_veo_gcs_output_is_downloaded_with_the_bearer_token(tmp_path):
    got = []
    http = FakeHttp({("POST", ":predictLongRunning"): [(200, {"name": OP})],
                     ("POST", ":fetchPredictOperation"): [done([{"gcsUri": "gs://bkt/out/a b/sample_0.mp4",
                                                                 "mimeType": "video/mp4"}])]})
    p = veo(tmp_path, http=http, fetch_bytes=lambda url, headers: got.append((url, headers)) or VIDEO)
    [c] = p.search("city at night", reel="r", clip="a", storage_uri="gs://bkt/out/")
    assert p.fetch(c, approved=True).read_bytes() == VIDEO
    assert got == [("https://storage.googleapis.com/storage/v1/b/bkt/o/out%2Fa%20b%2Fsample_0.mp4?alt=media",
                    {"Authorization": "Bearer ya29.test-token", "x-goog-user-project": "demo-project"})]
    assert p.budget.state(c.extra["request_id"])["approved_by"] == "studio (approved=True)"


def test_veo_timeout_resumes_the_same_job_without_paying_again(tmp_path):
    bud = budget(tmp_path)
    running = (200, {"name": OP})
    http = FakeHttp({("POST", ":predictLongRunning"): [(200, {"name": OP})],
                     ("POST", ":fetchPredictOperation"): [running, running, running, done()]})
    p = veo(tmp_path, http=http, bud=bud, poll_timeout=8)
    [c] = p.search("rocket", reel="r", clip="a")
    bud.approve(c.extra["request_id"])
    with pytest.raises(B.GenerationTimeout):
        p.fetch(c)
    assert bud.state(c.extra["request_id"])["state"] == "submitted"
    assert bud.summary()["spent_today_usd"] == 0.40           # counted while running
    again = veo(tmp_path, http=http, bud=bud, poll_timeout=60)   # a later run / restarted server
    assert again.fetch(c).read_bytes() == VIDEO
    assert len(http.hits(":predictLongRunning")) == 1


def test_veo_refused_request_is_refunded_and_filtered_clip_still_counts(tmp_path):
    bad = FakeHttp({("POST", ":predictLongRunning"): [(400, {"error": {"code": 400, "message": "bad aspect"}})]})
    p = veo(tmp_path, http=bad)
    [c] = p.search("rocket", reel="r1", clip="a")
    with pytest.raises(B.SubmitRejected):
        p.fetch(c, approved=True)
    assert p.budget.state(c.extra["request_id"])["charged"] is False and p.budget.summary()["spent_today_usd"] == 0
    with pytest.raises(B.ApprovalRequired, match="settled"):
        p.fetch(c, approved=True)                                # retry needs a new quote (attempt + 1)
    filt = FakeHttp({("POST", ":predictLongRunning"): [(200, {"name": OP})],
                     ("POST", ":fetchPredictOperation"): [done([], raiMediaFilteredCount=1,
                                                               raiMediaFilteredReasons=["celebrity likeness"])]})
    q = veo(tmp_path, http=filt, bud=p.budget)
    [c2] = q.search("rocket", reel="r2", clip="a", attempt=1)
    assert c2.id != c.id
    with pytest.raises(B.GenerationFailed, match="celebrity likeness"):
        q.fetch(c2, approved=True)
    assert p.budget.state(c2.extra["request_id"])["outcome"] == "filtered"
    assert p.budget.summary()["spent_today_usd"] == 0.40       # unknown charge: counted (fail closed)


def test_veo_probe_uses_free_reads_only(tmp_path):
    page1 = {"publisherModels": [{"name": "publishers/google/models/gemini-2.5-flash"},
                                 {"name": "publishers/google/models/veo-3.1-fast-generate-001"}], "nextPageToken": "p2"}
    page2 = {"publisherModels": [{"name": "publishers/google/models/veo-3.1-generate-001"},
                                 {"name": "publishers/google/models/veo-3.1-lite-generate-001"}]}
    bucket = lambda m, n, r="us-central1": {"effectiveLimit": n, "dimensions": {"region": r, "base_model": m}}  # noqa
    quota = {"metrics": [{"metric": "aiplatform.googleapis.com/long_running_online_prediction_requests_per_base_model",
                          "consumerQuotaLimits": [{"quotaBuckets": [
                              {"effectiveLimit": 5, "dimensions": {"region": "us-east1"}},
                              bucket("veo-3.1-fast-generate-001", "50"), bucket("veo-2.0-generate-001", "10")]}]}]}
    gone = (404, {"error": {"code": 404, "message": "Publisher Model ... is not found."}})
    http = FakeHttp({("GET", "pageToken=p2"): [(200, page2)], ("GET", "publishers/google/models?"): [(200, page1)],
                     ("GET", "/models/veo-3.1-lite"): [(200, {"launchStage": "PUBLIC_PREVIEW"})],
                     ("GET", "/models/veo-3.1-"): [(200, {"launchStage": "GA"})],
                     ("GET", "/models/veo-"): [gone], ("GET", "consumerQuotaMetrics"): [(200, quota)],
                     ("POST", ":testIamPermissions"): [(200, {"permissions": ["aiplatform.endpoints.predict"]})]})
    out = veo(tmp_path, http=http).probe()
    assert out["veo_models"] == ["veo-3.1-fast-generate-001", "veo-3.1-generate-001", "veo-3.1-lite-generate-001"]
    assert out["permissions"] == {"aiplatform.endpoints.predict": True} and out["ready"] is True
    assert out["model"] == {"id": "veo-3.1-fast-generate-001", "http": 200, "launch_stage": "GA", "quotable": True}
    assert out["models"]["veo-3.1-lite-generate-001"] == {"http": 200, "launch_stage": "PUBLIC_PREVIEW",
                                                          "quotable": False}
    assert {m for m, v in out["models"].items() if v["http"] == 404} == set(V.RETIRED)
    assert out["quota"] == {"veo-2.0-generate-001": {"us-central1": "10"},
                            "veo-3.1-fast-generate-001": {"us-central1": "50"}}
    assert {c.method for c in http.calls} <= {"GET", "POST"} and [c.url for c in http.calls if c.method == "POST"] \
        == ["https://cloudresourcemanager.googleapis.com/v1/projects/demo-project:testIamPermissions"]
    out = veo(tmp_path, http=http, location="europe-west4").probe()  # no Veo quota there: not ready
    assert out["ready"] is False


@pytest.mark.parametrize("stdout,code,want", [("my-proj\n", 0, "my-proj"), ("(unset)\n", 0, None), ("", 1, None)])
def test_veo_project_falls_back_to_gcloud_config(tmp_path, monkeypatch, stdout, code, want):
    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=code, stdout=stdout, stderr="")  # noqa: E731
    monkeypatch.setattr(V.shutil, "which", lambda name: "/usr/bin/gcloud")
    p = veo(tmp_path, run=run, project=None)
    assert calls == [["gcloud", "config", "get-value", "project"]]
    assert p.project == (want or "") and p.available is bool(want)
    assert V.VeoProvider.from_settings(env={"REEL_DIRECTOR_VEO_PROJECT": "env-proj"}, run=run).project == "env-proj"


def test_veo_cli_estimate_quote_and_refused_generate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REEL_DIRECTOR_PAID_LEDGER", str(tmp_path / "led.jsonl"))
    monkeypatch.setenv("REEL_DIRECTOR_MEDIA_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(V, "http_json", lambda *a, **k: pytest.fail("the CLI made a network call"))
    assert V.main(["estimate"]) == 0
    est = json.loads(capsys.readouterr().out)
    assert (est["model"], est["seconds"], est["resolution"], est["usd"]) == ("veo-3.1-fast-generate-001", 4, "1080p",
                                                                            0.40)
    assert V.main(["estimate", "--model", "veo-2.0-generate-001"]) == 2 and "catalog" in capsys.readouterr().err
    assert V.main(["quote", "rocket launching at dawn", "--reel", "real-1", "--clip", "s3.rocket"]) == 0
    q = json.loads(capsys.readouterr().out)
    assert q["usd"] == 0.40 and q["approve"].endswith(q["request_id"]) and q["then"].endswith(q["request_id"])
    assert V.main(["generate", q["request_id"]]) == 2              # quoted, never approved: refused, nothing sent
    assert "not approved" in capsys.readouterr().err
    assert [e["event"] for e in B.Budget(tmp_path / "led.jsonl").events()] == ["quote"]


def test_select_pick_keeps_the_paid_quote_and_fetch_needs_approval(tmp_path, monkeypatch):
    from reel_director.media import select as S
    monkeypatch.setattr(V.VeoProvider, "available", True)          # hermetic: no gcloud lookup
    http = FakeHttp({("POST", ":predictLongRunning"): [(200, {"name": OP})],
                     ("POST", ":fetchPredictOperation"): [done()]})
    p = veo(tmp_path, http=http)
    pk = S.pick("rocket launching", "video", {"veo": p}, ["veo"])
    assert pk.best is not None and pk.best.cand.provider == "veo" and pk.best.cand.cost_usd == 0.40
    d = pk.to_dict()["chosen"]
    with pytest.raises(BaseApprovalRequired):
        S.fetch(d, providers={"veo": p})
    assert http.calls == []
    assert S.fetch(d, approved=True, providers={"veo": p}).read_bytes() == VIDEO
    assert len(http.hits(":predictLongRunning")) == 1


# ---- budget / ledger ----------------------------------------------------------------------------------------------
def q(bud, usd, reel="r", clip="a", provider="veo"):
    return bud.quote(provider, "m", {"prompt": clip, "n": usd}, usd=usd, seconds=4, reel=reel, clip=clip)


def test_caps_per_reel_daily_and_one_paid_clip(tmp_path):
    clock = Clock()
    bud = budget(tmp_path, clock)
    a = q(bud, 3.0, clip="a")
    bud.approve(a.request_id)
    with pytest.raises(B.BudgetExceeded, match="1 paid clip"):
        bud.approve(q(bud, 1.0, clip="b").request_id)
    roomy = budget(tmp_path, clock, max_paid_clips_per_reel=5)
    with pytest.raises(B.BudgetExceeded, match="per-reel cap"):
        roomy.approve(q(roomy, 2.5, clip="c").request_id)       # 3.0 reserved + 2.5 > 5.0
    for i in range(4):                                            # 3 + 4 x 4 = 19 today
        roomy.approve(q(roomy, 4.0, reel=f"reel{i}").request_id)
    with pytest.raises(B.BudgetExceeded, match="daily cap"):
        roomy.approve(q(roomy, 1.5, reel="reel9").request_id)
    assert roomy.summary()["reserved_usd"] == 19.0
    for ev in roomy.events():
        if ev["event"] == "approve":
            roomy.begin(ev["request_id"])
    assert roomy.summary()["spent_today_usd"] == 19.0 and roomy.summary()["reserved_usd"] == 0
    clock.t += 86400                                              # next day: daily cap resets, reel caps don't
    roomy.approve(q(roomy, 4.0, reel="reel9").request_id)
    with pytest.raises(B.BudgetExceeded, match="per-reel"):
        roomy.approve(q(roomy, 2.5, reel="reel0", clip="z").request_id)


def test_unscoped_quotes_never_lock_out_other_reels_but_the_daily_cap_holds(tmp_path):
    bud = budget(tmp_path)                                        # select.pick passes no reel id -> reel ""
    for clip in ("rocket", "clock", "money"):
        bud.begin(bud.approve(q(bud, 4.0, reel="", clip=clip).request_id).request_id)
    with pytest.raises(B.BudgetExceeded, match="per-reel cap"):
        bud.approve(q(bud, 5.5, reel="", clip="too-big").request_id)  # one unscoped clip is still <= the reel cap
    bud.approve(q(bud, 4.0, reel="", clip="fourth").request_id)       # 12 spent + 4 reserved = 16
    with pytest.raises(B.BudgetExceeded, match="daily cap"):
        bud.approve(q(bud, 4.5, reel="", clip="fifth").request_id)
    named = q(bud, 1.0, reel="real-1", clip="a")
    bud.approve(named.request_id)                                  # a scoped reel is unaffected by the unscoped ones
    with pytest.raises(B.BudgetExceeded, match="1 paid clip"):
        bud.approve(q(bud, 1.0, reel="real-1", clip="b").request_id)


def test_approval_is_single_use_expires_and_needs_a_price(tmp_path):
    clock = Clock()
    bud = budget(tmp_path, clock)
    a = q(bud, 1.0)
    with pytest.raises(B.ApprovalRequired):
        bud.begin(a.request_id)
    bud.approve(a.request_id)
    bud.begin(a.request_id)
    with pytest.raises(B.ApprovalRequired, match="submitted"):
        bud.begin(a.request_id)
    b = q(bud, 1.0, reel="other")
    bud.approve(b.request_id)
    clock.t += B.APPROVAL_TTL_S + 1
    assert bud.state(b.request_id)["state"] == "expired"
    with pytest.raises(B.ApprovalRequired, match="expired"):
        bud.begin(b.request_id)
    bud.approve(b.request_id)
    bud.begin(b.request_id)
    nop = bud.quote("higgsfield", "m", {"p": 1}, usd=None, seconds=4, reel="x", clip="y")
    with pytest.raises(B.BudgetError, match="no price"):
        bud.approve(nop.request_id)
    bud.reject(q(bud, 1.0, reel="z").request_id)
    with pytest.raises(B.ApprovalRequired, match="rejected"):
        bud.begin(B.request_id_for("veo", "m", {"prompt": "a", "n": 1.0}, "z", "a"))


def test_ledger_is_deterministic_and_fails_closed(tmp_path):
    bud = budget(tmp_path)
    a, again = q(bud, 1.0), q(bud, 1.0)
    assert a.request_id == again.request_id == B.request_id_for("veo", "m", {"prompt": "a", "n": 1.0}, "r", "a")
    assert len(bud.events()) == 1
    with bud.ledger.open("a") as f:
        f.write("{not json\n")
    with pytest.raises(B.LedgerError):
        bud.approve(a.request_id)
    assert B.default_ledger_path({"REEL_DIRECTOR_CACHE": "/x"}).as_posix() == "/x/media/paid-ledger.jsonl"


def test_budget_cli_approve_and_summary(tmp_path, capsys):
    bud = budget(tmp_path)
    a = q(bud, 0.4)
    assert B.main(["--ledger", str(bud.ledger), "approve", a.request_id]) == 0
    assert "approved" in capsys.readouterr().out and bud.state(a.request_id)["approved_by"] == "founder"
    assert B.main(["--ledger", str(bud.ledger), "approve", "nope"]) == 2
    assert B.main(["--ledger", str(bud.ledger), "summary", "--reel", "r"]) == 0
    assert json.loads(capsys.readouterr().out)["per_reel_cap_usd"] == 5.0


# ---- Higgsfield -----------------------------------------------------------------------------------------------------
def hf(tmp_path, http=None, key="kid:ksecret", bud=None, got=None, mono=None):
    mono = mono or Clock(0.0)
    return H.HiggsfieldProvider(key=key, budget=bud or budget(tmp_path), cache=MediaCache(tmp_path / "cache"),
                                http=http or FakeHttp(), sleep=mono.sleep, clock=mono,
                                fetch_bytes=lambda url, headers: (got.append((url, headers)) if got is not None
                                                                  else None) or VIDEO)


def test_higgsfield_without_a_key_is_inactive(tmp_path):
    p = hf(tmp_path, key=None)
    assert not p.available and p.search("rocket") == [] and "HF_KEY" in p.status()["setup"]
    assert H.credential(env={"HF_API_KEY": "id", "HF_API_SECRET": "sec"}) == "id:sec"
    assert H.credential(env={"HF_KEY": "a:b", "HF_API_KEY": "id", "HF_API_SECRET": "s"}) == "a:b"
    assert H.credential(env={"HF_API_KEY_ID": "kid", "HF_API_KEY_SECRET": "ks"}) == "kid:ks"   # docs' curl names
    assert H.credential(env={"HF_CREDENTIALS": "x:y"}) == "x:y" and H.credential(env={}) is None
    assert H.credential({"media": {"higgsfield_key": "c:d"}}, env={}) == "c:d"


def test_higgsfield_quote_uses_the_free_estimate_endpoint(tmp_path):
    http = FakeHttp({("POST", "/estimate/bytedance/seedance-2.0/text-to-video"): [
        (200, {"credits": "30.000", "usd": "1.875"})]})
    p = hf(tmp_path, http=http)
    [c] = p.search("rocket launching", reel="r", clip="a")
    [call] = http.calls
    assert call.body == {"prompt": "rocket launching", "duration": 4, "generate_audio": False, "resolution": "1080p",
                         "aspect_ratio": "9:16"}
    assert call.headers["Authorization"] == "Key kid:ksecret"
    assert (c.cost_usd, c.w, c.h, c.license) == (1.875, 1080, 1920, "original") and "30.000 credits" in \
        c.extra["price_basis"]
    kling = H.build_args(H.make_spec("x", model="kling-video/v3.0/std/text-to-video", seconds=2.2))
    assert kling == {"prompt": "x", "duration": 3, "sound": "off", "aspect_ratio": "9:16"}


def test_higgsfield_approved_flow_is_idempotent_and_keeps_the_key_off_the_cdn(tmp_path):
    got = []
    st = lambda s, **kw: (200, {"status": s, "request_id": HF_ID, **kw})  # noqa: E731
    http = FakeHttp({("POST", "/estimate/"): [(200, {"credits": "30", "usd": "1.875"})],
                     ("POST", "api.higgsfield.ai/bytedance/seedance-2.0/text-to-video"): [st("queued")],
                     ("GET", f"/requests/{HF_ID}/status"): [st("queued"), st("in_progress"), st(
                         "completed", video={"url": "https://cdn.higgsfield.ai/out/clip.mp4"})]})
    p = hf(tmp_path, http=http, got=got)
    [c] = p.search("rocket", reel="r", clip="a")
    with pytest.raises(B.ApprovalRequired):
        p.fetch(c)
    assert not http.hits("/requests/") and len(http.calls) == 1
    path = p.fetch(c, approved=True)
    assert path.read_bytes() == VIDEO and json.loads(path.with_suffix(".json").read_text())["hf_request_id"] == HF_ID
    [sub] = [x for x in http.calls if x.url.endswith("/bytedance/seedance-2.0/text-to-video") and "estimate" not in x.url]
    assert sub.headers["Idempotency-Key"] == f"rd-{c.extra['request_id']}"
    assert got == [("https://cdn.higgsfield.ai/out/clip.mp4", {})]
    assert p.budget.state(c.extra["request_id"])["charged"] is True and p.budget.summary()["spent_today_usd"] == 1.875


def test_higgsfield_nsfw_is_refunded_and_bad_urls_refused(tmp_path):
    http = FakeHttp({("POST", "/estimate/"): [(200, {"credits": "30", "usd": "1.875"})],
                     ("POST", "/text-to-video"): [(200, {"status": "queued", "request_id": HF_ID})],
                     ("GET", "/status"): [(200, {"status": "nsfw", "request_id": HF_ID})]})
    p = hf(tmp_path, http=http)
    [c] = p.search("rocket", reel="r", clip="a")
    with pytest.raises(B.GenerationFailed):
        p.fetch(c, approved=True)
    s = p.budget.state(c.extra["request_id"])
    assert (s["outcome"], s["charged"]) == ("filtered", False) and p.budget.summary()["spent_today_usd"] == 0
    http.routes[("GET", "/status")] = [(200, {"status": "completed", "video": {"url": "http://evil.example/x.mp4"}})]
    [c2] = p.search("rocket", reel="r2", clip="a", attempt=1)
    with pytest.raises(H.HiggsfieldError, match="https"):
        p.fetch(c2, approved=True)


def test_higgsfield_image_to_video_uploads_without_the_api_key(tmp_path):
    img = tmp_path / "still.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")
    http = FakeHttp({("POST", "/files/generate-upload-url"): [(200, {
        "public_url": "https://cdn.higgsfield.ai/up/still.jpg", "upload_url": "https://upload.example/put?sig=1",
        "upload_headers": {"Content-Type": "image/jpeg"}})], ("PUT", "upload.example"): [(200, {})],
        ("POST", "/estimate/bytedance/seedance-2.0/image-to-video"): [(200, {"credits": "40", "usd": "2.5"})]})
    p = hf(tmp_path, http=http)
    [c] = p.search("slow push-in", reel="r", clip="a", image=img)
    put = http.hits("upload.example")[0]
    assert put.body == img.read_bytes() and "Authorization" not in put.headers
    assert http.hits("/estimate/")[0].body["image_url"] == "https://cdn.higgsfield.ai/up/still.jpg"
    assert c.cost_usd == 2.5 and c.extra["model"] == "bytedance/seedance-2.0/image-to-video"
    with pytest.raises(H.HiggsfieldError, match="needs an input image"):
        H.make_spec("x", model="bytedance/seedance-2.0/image-to-video")
