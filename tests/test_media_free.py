"""v4 media B-roll, free-stock team: interface, licenses, cache, ranking/segment/normalize, every free/keyed source.

No network: FakeHttp serves recorded fixtures (tests/fixtures/media; Commons/NASA/Archive recorded live on
2026-10-20, Openverse/Pixabay/Unsplash/Coverr shaped from their API docs). ffmpeg builds tiny local clips.
"""
import copy
import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

import pytest

from reel_director.media import license as L
from reel_director.media import providers as R
from reel_director.media import select as S
from reel_director.media.base import (ApprovalRequired, Candidate, Http, Provider, ProviderError, pick_rendition,
                                      redact, setting, strip_utm)
from reel_director.media.cache import MediaCache, default_root, ext_for
from reel_director.media.providers import coverr, library, nasa, openverse, pixabay, unsplash, webcapture
from reel_director.media.providers import wikimedia

FX = Path(__file__).parent / "fixtures" / "media"


def fx(name):
    d = json.loads((FX / name).read_text())
    if isinstance(d, dict):
        d.pop("_note", None)
    return d


class FakeHttp(Http):
    def __init__(self, routes=(), files=None):
        super().__init__(retries=0)
        self.routes, self.files, self.calls, self.pings, self.downloads = list(routes), files or {}, [], [], []

    def get_json(self, url, params=None, headers=None):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        self.calls.append((url, dict(headers or {})))
        for sub, payload in self.routes:
            if sub in url:
                return payload(url) if callable(payload) else copy.deepcopy(payload)
        raise ProviderError(f"no fixture for {url}")

    def download(self, url, dest, headers=None, max_bytes=1 << 30):
        self.downloads.append((url, dict(headers or {})))
        dest.write_bytes(next((v for k, v in self.files.items() if k in url), b"\xff\xd8" + url.encode() * 40))
        return "image/jpeg"

    def ping(self, url, method="GET", headers=None):
        self.pings.append((method, url, dict(headers or {})))
        return 204


@pytest.fixture
def cache(tmp_path):
    return MediaCache(tmp_path / "cache", cap_bytes=1 << 30)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def clip(path, cut=1.0, total=2.0, size="160x90"):
    """red for `cut` s, then a test pattern: one hard scene cut at `cut`."""
    ffmpeg("-f", "lavfi", "-i", f"color=c=red:s={size}:d={cut}:r=30", "-f", "lavfi",
           "-i", f"testsrc2=s={size}:d={total - cut}:r=30", "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
           "-map", "[v]", "-pix_fmt", "yuv420p", str(path))
    return path


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    return d["streams"][0], float(d["format"].get("duration", 0))


# --- package, interface ----------------------------------------------------------------------------------------

def test_media_duration_still_importable_from_the_package():
    from reel_director import compiler  # noqa: F401  (imports `from .media import media_duration`)
    from reel_director.media import media_duration
    assert callable(media_duration)


def test_candidate_roundtrip_redact_and_settings():
    c = Candidate(id="x:1", provider="x", kind="image", title="t", url="u", tags=("a",), extra={"k": 1})
    assert Candidate.from_dict({**c.to_dict(), "unknown": 1}) == c
    assert redact("https://pixabay.com/api/?key=SECRET&q=clock") == "https://pixabay.com/api/?key=***&q=clock"
    assert strip_utm("https://u.org/a.jpg?utm_source=x&w=1") == "https://u.org/a.jpg?w=1"
    s = {"media": {"pixabay_key": "from-settings"}}
    assert setting(s, "pixabay_key", ("PIXABAY_API_KEY",), env={}) == "from-settings"
    assert setting(s, "pixabay_key", ("PIXABAY_API_KEY",), env={"PIXABAY_API_KEY": "env"}) == "env"
    assert setting({"media.coverr_key": "flat"}, "coverr_key", env={}) == "flat"


def test_brief_pick_module_fetch_windows_and_paid_guard(cache, tmp_path):
    """mediaplan calls select.pick(brief dict) -> media.json dict and select.fetch(candidate dict) -> path."""
    provs = {"wikimedia": wikimedia.provider(None, http=FakeHttp([("commons", fx("wikimedia_video_clock.json"))]))}
    d = S.pick({"query": "clock", "kind": "video", "providers": ["wikimedia"], "orientation": "any",
                "duration": [2.0, 10.0], "min_short_side": 1080}, providers=provs)
    ch, got = d["chosen"], []

    class P(Provider):
        def fetch(self, c, segment=None, approved=False):
            self.guard(c, approved)
            got.append(segment)
            return tmp_path / "w.mkv"
    assert ch["provider"] == "wikimedia" and d["credits"] and ch["duration"] > S.LONG_S
    assert S.fetch(ch, providers={"wikimedia": P()}) == tmp_path / "w.mkv"
    assert got == [(round(ch["duration"] * 0.25, 3), round(ch["duration"] * 0.25 + S.WINDOW_S, 3))]
    (tmp_path / "f.mkv").write_bytes(b"1")
    assert S.fetch({**ch, "path": str(tmp_path / "f.mkv")}) == tmp_path / "f.mkv"
    gen = Candidate(id="claude_clip:1", provider="claude_clip", kind="video", title="clock", url="u", w=1080,
                    h=1920, duration=3, license="original")
    assert S.score(gen, "clock").score == pytest.approx(0.85 * S.score(Candidate.from_dict(
        {**gen.to_dict(), "provider": "p"}), "clock").score)
    with pytest.raises(ApprovalRequired):
        S.fetch({**gen.to_dict(), "cost_usd": 1.2}, providers={"claude_clip": P()})
    with pytest.raises(ApprovalRequired):
        type("Paid", (P,), {"paid": True})().fetch(gen)


def test_pick_rendition_covers_the_reel_frame():
    rends = [{"w": 640, "h": 425}, {"w": 1920, "h": 1312}, {"w": 4288, "h": 2848}]
    assert pick_rendition(rends, 1080)["w"] == 1920                     # short side reaches 1080
    assert pick_rendition(rends, 1080, "portrait")["w"] == 4288         # 1312 tall would upscale a 1920 crop
    assert pick_rendition([{"w": 1920, "h": 1080}, {"w": 854, "h": 480}], 1080, "portrait")["w"] == 1920


# --- licenses --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,url,ver,lid,ok,sa", [
    ("by", "", "4.0", "cc-by-4.0", True, False), ("by-sa", "", "3.0", "cc-by-sa-3.0", True, True),
    ("cc0", "", "", "cc0-1.0", True, False), ("pdm", "", "", "pdm-1.0", True, False),
    ("by-nc", "", "4.0", "cc-by-nc-4.0", False, False), ("by-nd", "", "2.0", "cc-by-nd-2.0", False, False),
    ("CC BY-SA 4.0", "", "", "cc-by-sa-4.0", True, True), ("Public domain", "", "", "pd", True, False),
    ("GFDL|CC-BY-SA-3.0", "", "", "cc-by-sa-3.0", True, True), ("GFDL", "", "", "gfdl", False, True),
    ("", "http://creativecommons.org/licenses/publicdomain/", "", "pd", True, False),
    ("", "http://creativecommons.org/licenses/by-nc/3.0/", "", "cc-by-nc-3.0", False, False),
    ("", "https://creativecommons.org/publicdomain/mark/1.0/", "", "pdm-1.0", True, False),
    ("CC-BY-3.0", "", "", "cc-by-3.0", True, False), ("original", "", "", "original", True, False),
    ("PD-USGov-NASA", "", "", "pd", True, False), ("CC BY-NC-SA 2.0", "", "", "cc-by-nc-sa-2.0", False, True),
    ("Creative Commons Attribution-Share Alike 3.0", "", "", "cc-by-sa-3.0", True, True),
    ("Own work, CC BY", "", "", "cc-by", True, False), ("Copyrighted free use", "", "", "unknown", False, False),
    ("", "", "", "unknown", False, False), ("pixabay", "", "", "pixabay", True, False),
])
def test_license_normalize(raw, url, ver, lid, ok, sa):
    lic = L.normalize(raw, url, ver)
    assert (lic.id, lic.allowed, lic.share_alike) == (lid, ok, sa)
    assert L.info(lic.id).id == lic.id                                  # ids round-trip


def test_attribution_and_credits_file(tmp_path):
    by = L.attribution("Clock", "Diliff", "https://c.org/p", L.normalize("CC BY 3.0"), "Wikimedia Commons")
    assert by == ('"Clock" by Diliff via Wikimedia Commons (https://c.org/p), CC BY 3.0 '
                  '(https://creativecommons.org/licenses/by/3.0/), modified (cropped, trimmed, graded)')
    assert "Photo by Jeff on Unsplash" in L.attribution("Desk", "Jeff", "", L.normalize("unsplash"))
    mk = lambda i, lic, a="": Candidate(id=i, provider="p", kind="image", title=i, url=i, license=lic, attribution=a)
    picks = [mk("a", "cc-by-sa-4.0", "A line"), mk("a", "cc-by-sa-4.0", "A line"), mk("o", "own"), mk("p", "pd")]
    assert L.credits(picks) == ["A line", '"p", Public domain']
    out = L.write_credits(tmp_path / "renders" / "reel.credits.txt", picks, "reel")
    text = out.read_text()
    assert text.startswith("B-roll credits — reel\n") and "Share-alike" in text and "CC BY-SA 4.0" in text
    assert L.write_credits(tmp_path / "again.txt", picks, "reel").read_text() == text   # deterministic


# --- cache -----------------------------------------------------------------------------------------------------

def test_cache_content_addressing_lookup_and_json(cache, tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(b"same"), b.write_bytes(b"same")
    pa, pb = cache.put(a, "key-a", {"title": "A"}), cache.put(b, "key-b", {"title": "B"}, move=False)
    assert pa == pb and pa.parent.parent.name == "files" and not a.exists() and b.exists()
    assert cache.meta(pa)["keys"] == ["key-a", "key-b"] and cache.lookup("key-b") == pa
    assert cache.lookup("missing") is None
    http = FakeHttp()
    p1 = cache.fetch_url("https://x.org/img.jpg?key=SECRET", http)
    assert cache.fetch_url("https://x.org/img.jpg?key=SECRET", http) == p1 and len(http.downloads) == 1
    assert "SECRET" not in p1.with_suffix(".json").read_text()
    cache.json_put("api:q", {"v": 1})
    assert cache.json_get("api:q") == {"v": 1} and cache.json_get("api:q", ttl=1e-9) is None
    assert ext_for("https://x/a.WEBM") == ".webm" and ext_for("https://x/a", "video/mp4") == ".mp4"


def test_cache_lru_eviction_respects_keep_and_recent(tmp_path, monkeypatch):
    c = MediaCache(tmp_path, cap_bytes=10 ** 9)
    paths = []
    for i in range(3):
        f = tmp_path / f"{i}.bin"
        f.write_bytes(bytes([i]) * 1000)
        paths.append(c.put(f, f"k{i}"))
        os.utime(paths[-1], (time.time() - 7200 + i, time.time() - 7200 + i))
    assert c.evict(cap=2500, keep={paths[0].stem}) == [paths[1].stem]   # oldest kept -> next oldest goes
    os.utime(paths[2], None)                                            # just used: protected
    assert c.evict(cap=100) == [paths[0].stem] and paths[2].exists() and c.lookup("k1") is None


def test_default_root(monkeypatch, tmp_path):
    assert default_root({"RD_MEDIA_CACHE": str(tmp_path)}) == tmp_path
    monkeypatch.setattr(os.path, "ismount", lambda p: False)
    assert default_root({}).parts[-2:] == ("reel-director", "media")


def test_cache_fetch_window_local_clip(cache, tmp_path):
    src = clip(tmp_path / "src.mp4", 1.0, 3.0)
    w = cache.fetch_window(src.as_uri(), (1.2, 2.2))
    st, dur = probe(w)
    assert w.suffix == ".mkv" and st["width"] == 160 and 0.9 <= dur <= 1.6
    assert cache.fetch_window(src.as_uri(), (1.2, 2.2)) == w


# --- free providers (recorded fixtures) -------------------------------------------------------------------------

def test_wikimedia_images_licenses_attribution_and_nc_rejected(cache):
    http = FakeHttp([("commons.wikimedia.org", fx("wikimedia_image_clock.json"))])
    got = wikimedia.provider(None, http=http, cache=cache).search("clock", "image", orientation="portrait")
    assert [c.license for c in got] == ["cc0-1.0", "cc-by-sa-4.0", "cc0-1.0", "cc-by-3.0"]   # synthetic NC dropped
    c = got[0]
    assert c.id == "wikimedia:23131866" and (c.w, c.h) == (1920, 2627) and "utm_" not in c.url + c.thumb
    assert "/1920px-" in c.url and c.extra["original_url"].endswith("IMG_0931_edit.jpg") and c.extra["orig_w"] == 3378
    assert c.creator == "Christoph Braun" and "filetype:bitmap" in urllib.parse.unquote_plus(http.calls[0][0])
    assert got[3].attribution.endswith("modified (cropped, graded)") and "via Wikimedia Commons" in got[3].attribution   # a still: not trimmed
    wikimedia.provider(None, http=http, cache=cache).search("clock", "image")
    assert len(http.calls) == 1                                          # second search: response cache


def test_wikimedia_video_picks_the_vp9_transcode_and_busy_retries(cache):
    http = FakeHttp([("commons.wikimedia.org", fx("wikimedia_video_clock.json"))])
    got = {c.title: c for c in wikimedia.provider(None, http=http).search("clock", "video", orientation="portrait")}
    k = got["Kremlin Clock chimes in 2012"]
    assert k.url.endswith("1080p.vp9.webm") and (k.w, k.h, k.duration) == (1920, 1080, 61.32) and k.license == "cc-by-4.0"
    busy = {"error": {"code": "cirrussearch-too-busy-error", "info": "busy"}}
    p = wikimedia.provider(None, http=FakeHttp([("commons", busy)]))
    p.retry_wait = 0
    with pytest.raises(ProviderError, match="too-busy"):
        p.search("clock")
    assert len(p.http.calls) == 2


def test_nasa_image_rendition_credit_and_third_party_filter():
    data = fx("nasa_image_laptop.json")
    http = FakeHttp([("images-api.nasa.gov", data)])
    got = nasa.provider(None, http=http).search("laptop", "image", orientation="portrait")
    c = got[0]
    assert c.url.endswith("~orig.jpg") and (c.w, c.h) == (4288, 2848) and c.license == "pd"
    assert c.creator == "NASA/JSC" and "NASA Image and Video Library" in c.attribution
    assert nasa.provider(None, http=http).search("laptop")[0].url.endswith("~large.jpg")   # no orientation
    data["collection"]["items"][0]["data"][0]["description"] += " Photo © Getty Images"
    assert len(nasa.provider(None, http=FakeHttp([("images-api", data)])).search("laptop")) == len(got) - 1


def test_nasa_video_resolve_reads_manifest_and_metadata():
    http = FakeHttp([("metadata.json", fx("nasa_video_metadata.json")), ("collection.json", fx("nasa_video_manifest.json")),
                     ("images-api.nasa.gov", fx("nasa_video_camera.json"))])
    p = nasa.provider(None, http=http)
    c = p.search("camera", "video")[0]
    assert c.url == "" and c.extra["files"]
    r = p.resolve(c)
    assert r.url.endswith("~orig.mp4") and "%20" in r.url and r.url.startswith("https://")
    assert (r.w, r.h, round(r.duration, 2)) == (1920, 1080, 28.57)


def test_openverse_filters_and_rejects_nd():
    http = FakeHttp([("api.openverse.org", fx("openverse_images_laptop.json"))])
    got = openverse.provider(None, http=http).search("laptop", "image", orientation="portrait")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(http.calls[0][0]).query))
    assert q["license"] == "by,by-sa,cc0,pdm" and q["aspect_ratio"] == "tall" and q["filter_dead"] == "false"
    assert [c.license for c in got] == ["cc-by-2.0", "cc0-1.0"] and "Flickr via Openverse" in got[0].attribution
    assert openverse.provider(None, http=http).search("laptop", "video") == []


# --- keyed providers (inactive without a key) -----------------------------------------------------------------

@pytest.mark.parametrize("mod,env", [(pixabay, "PIXABAY_API_KEY"), (unsplash, "UNSPLASH_ACCESS_KEY"),
                                     (coverr, "COVERR_API_KEY")])
def test_keyed_sources_are_inactive_without_a_key(mod, env, monkeypatch):
    monkeypatch.delenv(env, raising=False)
    http = FakeHttp()
    p = mod.provider({}, http=http)
    assert not p.available and env in p.status()["setup"]
    assert p.search("clock", p.kinds[0]) == [] and http.calls == []
    monkeypatch.setenv(env, "k")
    assert mod.provider({}).available


def test_pixabay_images_videos_and_key_never_on_disk(cache):
    http = FakeHttp([("api/videos/", fx("pixabay_videos_clock.json")), ("pixabay.com/api/", fx("pixabay_images_clock.json"))])
    p = pixabay.provider({"media": {"pixabay_key": "SECRET-KEY"}}, http=http, cache=cache)
    imgs = p.search("clock", "image", orientation="portrait")
    assert [(c.w, c.h) for c in imgs] == [(853, 1280), (3000, 3000)] and imgs[1].url.endswith("aa.jpg")
    assert imgs[0].license == "pixabay" and "from Pixabay" in imgs[0].attribution
    vids = p.search("clock", "video", orientation="portrait")
    assert len(vids) == 1 and vids[0].extra["rendition"] == "large" and vids[0].duration == 12
    assert p.search("clock", "video", orientation=None)[0].extra["rendition"] == "medium"
    assert "video_type=film" in http.calls[1][0] and "q=clock" in http.calls[0][0]
    f = p.fetch(imgs[0])
    assert p.fetch(imgs[0]) == f and p.cache_key(imgs[0]) == "pixabay:image:195893:853x1280"
    assert not any("SECRET-KEY" in x.read_text(errors="ignore") for x in cache.root.rglob("*.json"))


def test_unsplash_headers_sizes_attribution_and_download_tracking(cache):
    http = FakeHttp([("api.unsplash.com/search/photos", fx("unsplash_search_laptop.json"))])
    p = unsplash.provider({}, key="KEY", http=http, cache=cache)
    c = p.search("laptop", "image", orientation="portrait")[0]
    assert http.calls[0][1] == {"Authorization": "Client-ID KEY", "Accept-Version": "v1"}
    assert "orientation=portrait" in http.calls[0][0] and "content_filter=high" in http.calls[0][0]
    assert "ixid=abc123" in c.url and "w=1620" in c.url and (c.w, c.h) == (1620, 2430)
    assert c.attribution.startswith('"A laptop on a desk with an editing timeline" — Photo by Jeff Sheldon on Unsplash')
    assert "utm_source=reel_director&utm_medium=referral" in c.source_page
    p.fetch(c), p.fetch(c)
    assert len(http.downloads) == 1 and http.pings == [("GET", c.extra["download_location"],
                                                        {"Authorization": "Client-ID KEY", "Accept-Version": "v1"})]


def test_coverr_bearer_vertical_first_and_download_stats(cache):
    http = FakeHttp([("api.coverr.co/videos", fx("coverr_videos_clock.json"))])
    p = coverr.provider({}, key="KEY", http=http, cache=cache)
    got = p.search("clock", "video", orientation="portrait")
    assert http.calls[0][1] == {"Authorization": "Bearer KEY"} and "urls=true" in http.calls[0][0]
    assert [c.id for c in got] == ["coverr:Vert1cal99", "coverr:aB3dE5fG7h"] and got[1].url.endswith("download?token=JWT1")
    p.fetch(got[1], segment=(1, 3)), p.fetch(got[1])
    assert len(http.downloads) == 1 and http.pings == [("PATCH", "https://api.coverr.co/videos/aB3dE5fG7h/stats/downloads",
                                                        {"Authorization": "Bearer KEY"})]


# --- library + webcapture ----------------------------------------------------------------------------------------

def test_library_matches_path_words_and_sidecars(tmp_path, cache):
    root = tmp_path / "lib"
    (root / "office").mkdir(parents=True)
    (root / "office" / "laptop-typing.mp4").write_bytes(b"v")
    (root / "office" / "clock.jpg").write_bytes(b"i")
    (root / "nc.jpg").write_bytes(b"i")
    (root / "nc.jpg.json").write_text(json.dumps({"tags": ["clock"], "license": "CC BY-NC 4.0"}))
    (root / ".hidden").mkdir()
    (root / ".hidden" / "clock.jpg").write_bytes(b"i")
    p = library.provider({"media": {"library": str(root)}}, cache=cache, probe=lambda f: (1920, 1080, 6.0))
    assert p.available and not library.provider({"media": {"library": str(tmp_path / "nope")}}).available
    imgs = p.search("wall clock", "image")
    assert [c.id for c in imgs] == ["library:office/clock.jpg"] and imgs[0].license == "own" and imgs[0].attribution == ""
    vids = p.search("office laptop", "video")
    assert vids[0].id == "library:office/laptop-typing.mp4" and vids[0].duration == 6.0
    assert p.fetch(imgs[0]).read_bytes() == b"i"


def test_webcapture_only_urls_runs_once_and_reports_failure(cache):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        shots = Path(cmd[cmd.index("-o") + 1]) / "screenshots"
        shots.mkdir(parents=True)
        for n in ("scroll-000.png", "scroll-050.png", "full-page.png"):
            (shots / n).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, '{"ok":true}\n', "")
    p = webcapture.provider(None, cache=cache, run=run, probe=lambda f: (1440, 900, 0.0))
    p.exe = "hyperframes"
    assert p.search("laptop on desk") == [] and calls == []
    got = p.search("https://anvevoice.app")
    assert [c.title for c in got] == ["anvevoice.app (0% down)", "anvevoice.app (50% down)", "anvevoice.app (full page)"]
    assert got[0].license == "user-capture" and "--skip-vision" in calls[0] and got[2].extra["plate"]
    p.search("https://anvevoice.app")
    assert len(calls) == 1
    bad = webcapture.provider(None, cache=cache, run=lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, '{"ok":false,"error":"net::ERR"}', ""))
    bad.exe = "hyperframes"
    with pytest.raises(ProviderError, match="net::ERR"):
        bad.search("https://example.org/x")


def test_registry_build_status_order(monkeypatch):
    built = R.build(settings={}, http=FakeHttp())
    assert set(R.FREE + R.KEYED) <= set(built) and not built["pixabay"].available
    rows = {r["provider"]: r for r in R.status({}, names=R.FREE + R.KEYED)}
    assert rows["wikimedia"]["available"] and not rows["coverr"]["available"]
    assert R.order("video", built, prefer=["archive"])[:3] == ["archive", "wikimedia", "nasa"]
    monkeypatch.setattr(R, "load", lambda n: None)
    assert R.make("veo") is None and R.status({}, ["veo"])[0]["setup"] == "not installed"


# --- ranking, pick, vision ---------------------------------------------------------------------------------------

def test_tokens_relevance_quality_and_penalties():
    assert S.tokens("Editing the clocks, timelines!") == ["edit", "clock", "timeline"]
    mk = lambda **k: Candidate(**{"id": "p:1", "provider": "p", "kind": "image", "title": "", "url": "u", "license": "cc0", **k})
    assert S.relevance(mk(title="Wall clock"), "clock") == 1.0 and S.relevance(mk(tags=("clock",)), "clock") == 0.8
    assert S.quality(mk(w=1080, h=1920)) == 1.0 and S.quality(mk(w=1920, h=1080)) < 0.5
    assert S.quality(mk(w=1080, h=1920, extra={"restrictions": "personality"})) == 0.8
    assert S.quality(mk(kind="video", w=1080, h=1920, duration=1.0)) == 0.0
    assert S.quality(mk(kind="video", w=1080, h=1920, duration=1540, title="Around The Clock news")) == pytest.approx(0.56)
    art, photo = mk(title="Clock, folio from a manuscript", w=1080, h=1920), mk(id="p:2", title="Clock", w=1080, h=1920)
    assert S.score(art, "clock").parts["quality"] == 0.75 * S.score(photo, "clock").parts["quality"]
    assert S.score(art, "old manuscript clock").parts["quality"] == S.score(photo, "clock").parts["quality"]


def test_rank_dedupes_drops_disallowed_and_is_deterministic():
    http = FakeHttp([("commons", fx("wikimedia_image_clock.json"))])
    cands = wikimedia.provider(None, http=http).search("clock", "image", orientation="portrait")
    bad = Candidate(id="x:nc", provider="x", kind="image", title="clock", url="nc", license="cc-by-nc-4.0")
    r1 = S.rank(cands + cands[:1] + [bad], "clock", ["wikimedia"])
    assert len(r1) == 4 and "x:nc" not in [s.cand.id for s in r1]
    assert r1[0].cand.title.startswith("Pendulum clock")                  # CC0 photo beats the CC0 folio scan
    assert [s.cand.id for s in r1] == [s.cand.id for s in S.rank(list(reversed(cands)), "clock", ["wikimedia"])]


def test_pick_end_to_end_with_failing_source_and_media_json_shape():
    http = FakeHttp([("commons", fx("wikimedia_image_clock.json")), ("images-api", fx("nasa_image_laptop.json"))])

    class Down(Provider):
        name = "openverse"

        def search(self, *a, **k):
            raise ProviderError("HTTP 504")
    provs = {"wikimedia": wikimedia.provider(None, http=http), "nasa": nasa.provider(None, http=http), "openverse": Down()}
    pk = S.pick("clock", "image", providers=provs, alternates=2)
    d = pk.to_dict()
    assert d["chosen"]["provider"] == "wikimedia" and len(d["alternates"]) == 2 and d["credits"]
    assert any("openverse: ProviderError" in n for n in d["notes"]) and json.dumps(d)
    assert S.pick("zzzz", "video", providers={}).best is None


def test_vision_rerank_blends_scores_and_caches(cache):
    http = FakeHttp()
    cands = [Candidate(id=f"p:{i}", provider="p", kind="image", title="clock", url=f"https://x/{i}.jpg",
                       thumb=f"https://x/t{i}.jpg", w=1080, h=1920, license="cc0") for i in (1, 2)]
    ranked = S.rank(cands, "clock")
    runs = []

    def run(cmd, **kw):
        runs.append(cmd)
        assert "ANTHROPIC_API_KEY" not in kw["env"]                     # subscription only: never paid
        return subprocess.CompletedProcess(cmd, 0, 'Sure.\n{"scores": [{"i": 1, "relevance": 2, "quality": 3, '
                                                    '"text": true}, {"i": 2, "relevance": 9, "quality": 9}]}', "")
    hook = S.vision_rerank(cache, http, run=run)
    os.environ["ANTHROPIC_API_KEY"] = "sk-paid"
    try:
        out = hook(ranked, "clock")
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
    assert out[0].cand.id == ranked[1].cand.id and out[0].parts["vision"]["relevance"] == 9
    assert "--allowedTools" in runs[0] and "Read" in runs[0]
    assert [s.cand.id for s in hook(ranked, "clock")] == [s.cand.id for s in out] and len(runs) == 1
    assert S.parse_scores("no json") is None and "ANTHROPIC_API_KEY" not in S.claude_env()


def test_vision_failure_is_a_note_not_a_crash(cache):
    http = FakeHttp([("commons", fx("wikimedia_image_clock.json"))])
    fail = S.vision_rerank(cache, FakeHttp(), run=lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, "", "Failed to authenticate: OAuth session expired"))
    pk = S.pick("clock", "image", providers={"wikimedia": wikimedia.provider(None, http=http)}, vision=fail)
    assert pk.best.cand.title.startswith("Pendulum") and any("OAuth session expired" in n for n in pk.notes)


# --- segments + normalize ------------------------------------------------------------------------------------

def test_best_segment_stays_inside_a_shot_and_avoids_flags():
    s, e = S.best_segment(20.0, 3.0, cuts=[4.0, 12.0])
    assert 4.0 < s and e < 12.0 and e - s == 3.0
    flagged = S.best_segment(20.0, 3.0, cuts=[4.0, 12.0], flags=lambda t: {"faces": 2} if 4 < t < 12 else {})
    assert flagged[0] >= 12.0
    assert S.best_segment(2.0, 3.0) == (0.0, 2.0) and S.best_segment(3.0, 1.0) == (1.0, 2.0)
    assert S.best_segment(10.0, 3.0, cuts=[2.0, 4.0, 6.0, 8.0])[1] - S.best_segment(10.0, 3.0, cuts=[2.0, 4.0, 6.0, 8.0])[0] == 3.0


def test_scenes_normalize_clip_and_image_are_deterministic(tmp_path):
    src = clip(tmp_path / "src.mp4", 1.0, 2.0)
    assert [round(t, 1) for t in S.scenes(src)] == [1.0]
    g = S.grade_filter({"y": 60, "range": 100, "sat": 20}, {"y": 120, "range": 150, "sat": 40}, {"temp": 0.06, "sat": 1.05})
    assert g == "eq=brightness=0.080:contrast=1.120:saturation=1.260,colorbalance=rm=0.030:bm=-0.030:rh=0.018:bh=-0.018"
    a = S.normalize_clip(src, tmp_path / "a.mp4", (0.5, 1.5), w=108, h=192, grade=g)
    b = S.normalize_clip(src, tmp_path / "b.mp4", (0.5, 1.5), w=108, h=192, grade=g)
    st, dur = probe(a)
    assert (st["width"], st["height"], st["r_frame_rate"]) == (108, 192, "30/1") and abs(dur - 1.0) < 0.05
    assert a.read_bytes() == b.read_bytes()
    still = tmp_path / "still.png"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:d=0.1", "-frames:v", "1", str(still))
    for fit in ("cover", "contain"):
        st, _ = probe(S.normalize_image(still, tmp_path / f"{fit}.png", 108, 192, fit=fit, headroom=1.25))
        assert (st["width"], st["height"]) == (136, 240)
    stats = S.frame_stats(src, 1.2)
    assert stats["y"] > 0 and stats["sat"] > 0
