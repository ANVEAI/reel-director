"""v4 media: YouTube Creative-Commons provider (discovery via Data API v3, opt-in CC-BY download via yt-dlp).

No network: the API answers come from the fixtures below (shaped like YouTube Data API v3 search.list / videos.list
responses; errors as base.Http raises them) and yt-dlp/ffmpeg are a fake runner whose metadata was recorded from a
real `yt-dlp -J` of a CC-BY video."""
import hashlib
import json
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from reel_director.media.base import Candidate, ProviderError, redact
from reel_director.media.providers import youtube_cc as yt

SEARCH = {"kind": "youtube#searchListResponse", "items": [
    {"id": {"kind": "youtube#video", "videoId": "AAAAAAAAAA1"}, "snippet": {"title": "City time lapse"}},
    {"id": {"kind": "youtube#video", "videoId": "BBBBBBBBBB2"}, "snippet": {"title": "Standard licence"}},
    {"id": {"kind": "youtube#video", "videoId": "CCCCCCCCCC3"}, "snippet": {"title": "Live now"}},
    {"id": {"kind": "youtube#video", "videoId": "DDDDDDDDDD4"}, "snippet": {"title": "Too short"}},
    {"id": {"kind": "youtube#video", "videoId": "EEEEEEEEEE5"}, "snippet": {"title": "Night skyline 4K"}},
    {"id": {"kind": "youtube#channel", "channelId": "UCxxxx"}, "snippet": {"title": "a channel"}},
]}


def _video(vid, title, channel, dur, lic="creativeCommon", live="none", definition="hd"):
    return {"id": vid,
            "snippet": {"title": title, "channelTitle": channel, "channelId": "UC" + vid, "liveBroadcastContent": live,
                        "publishedAt": "2024-01-02T03:04:05Z", "tags": ["city", "timelapse"],
                        "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"},
                                       "maxres": {"url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"}}},
            "contentDetails": {"duration": dur, "definition": definition, "projection": "rectangular"},
            "status": {"license": lic}}


VIDEOS = {"kind": "youtube#videoListResponse", "items": [   # deliberately not in search order
    _video("EEEEEEEEEE5", "Night skyline 4K", "Skyline Studio", "PT2M10S", definition="sd"),
    _video("AAAAAAAAAA1", "City time lapse", "Urban Lens", "PT1M5S"),
    _video("BBBBBBBBBB2", "Standard licence", "Someone", "PT30S", lic="youtube"),
    _video("CCCCCCCCCC3", "Live now", "Live Cam", "P0D", live="live"),
    _video("DDDDDDDDDD4", "Too short", "Clips", "PT1S"),
]}
# the real 403 body the API returned for the gcloud token on 2026-10-20 (abridged)
SCOPE_403 = {"error": {"code": 403, "message": "Request had insufficient authentication scopes.",
                       "errors": [{"message": "Insufficient Permission", "domain": "global",
                                   "reason": "insufficientPermissions"}], "status": "PERMISSION_DENIED"}}
QUOTA_403 = {"error": {"code": 403, "message": "The request cannot be completed because you have exceeded your "
                       "<a href=\"/youtube/v3/getting-started#quota\">quota</a>.",
                       "errors": [{"domain": "youtube.quota", "reason": "quotaExceeded"}]}}
# recorded 2026-10-20 from `yt-dlp -J --skip-download https://www.youtube.com/watch?v=aqz-KE-bpKQ` (subset)
YTDLP_META = {"id": "aqz-KE-bpKQ", "title": "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film",
              "channel": "Blender", "uploader": "Blender",
              "license": "Creative Commons Attribution license (reuse allowed)",
              "duration": 635, "width": 3840, "height": 2160}


class Err:
    def __init__(self, code, body):
        self.code, self.body = code, body


class FakeHttp:
    """base.Http stand-in: get_json(url, params, headers); an Err answer raises like base.Http does."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url.rsplit("/", 1)[-1], dict(params or {}), dict(headers or {})))
        r = self.responses.pop(0)
        if isinstance(r, Err):
            full = url + "?" + urllib.parse.urlencode(params or {})
            raise ProviderError(f"HTTP {r.code} for {redact(full)}: {json.dumps(r.body)[:200]}")
        return r


class FakeRun:
    """subprocess.run stand-in: yt-dlp -J -> metadata, yt-dlp -o -> writes bytes (or fails with `fail` on stderr),
    ffmpeg -> writes the source bytes plus the cut range, gcloud -> a token."""

    def __init__(self, meta=YTDLP_META, payload=b"fake-mp4-bytes", token="tok", fail=None):
        self.meta, self.payload, self.token, self.fail, self.calls = meta, payload, token, fail, []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if cmd[:2] == ["gcloud", "auth"]:
            return subprocess.CompletedProcess(cmd, 0, self.token + "\n", "")
        if cmd[0] == "ffmpeg":
            src = Path(cmd[cmd.index("-i") + 1]).read_bytes()
            Path(cmd[-1]).write_bytes(src + f"|{cmd[cmd.index('-ss') + 1]}+{cmd[cmd.index('-t') + 1]}".encode())
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "-J" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.meta), "")
        if self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", self.fail)
        Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp4")).write_bytes(self.payload)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    @property
    def downloads(self):
        return [c for c in self.calls if c[0] == "yt-dlp" and "-o" in c]

    @property
    def trims(self):
        return [c for c in self.calls if c[0] == "ffmpeg"]


def provider(http=None, run=None, tmp=None, **kw):
    kw.setdefault("key", "test-key")
    return yt.YouTubeCC(http=http or FakeHttp(), run=run or FakeRun(), ytdlp="yt-dlp", ffmpeg="ffmpeg",
                        cache_dir=tmp, **kw)


def test_iso8601_durations():
    assert yt.iso8601_seconds("PT15S") == 15
    assert yt.iso8601_seconds("PT1M5S") == 65
    assert yt.iso8601_seconds("PT1H2M3S") == 3723
    assert yt.iso8601_seconds("P1DT1S") == 86401
    assert yt.iso8601_seconds("P0D") == 0
    for bad in ("", "P", "PT", "1M", "PTXS"):
        with pytest.raises(ValueError):
            yt.iso8601_seconds(bad)


def test_cc_by_detection_rejects_variants():
    assert yt.is_cc_by("Creative Commons Attribution license (reuse allowed)")
    assert yt.is_cc_by("CC BY 3.0") and yt.LICENSE.id == "cc-by-3.0" and yt.LICENSE.allowed
    for bad in (None, "", "Standard YouTube License", "CC BY-NC 4.0", "CC BY-SA 3.0", "CC BY-ND",
                "Creative Commons Attribution-NonCommercial", "Creative Commons Attribution-ShareAlike"):
        assert not yt.is_cc_by(bad), bad


def test_search_request_uses_cc_filter_and_key():
    http = FakeHttp(SEARCH, VIDEOS)
    provider(http).search("time lapse city", limit=2)
    (m1, q1, h1), (m2, q2, _) = http.calls
    assert m1 == "search" and m2 == "videos"
    assert q1["videoLicense"] == "creativeCommon" and q1["type"] == "video" and q1["q"] == "time lapse city"
    assert q1["key"] == "test-key" and q1["videoDefinition"] == "high" and q1["videoDuration"] == "short"
    assert q1["safeSearch"] == "strict" and q1["order"] == "relevance" and q1["maxResults"] == 4
    assert q2["part"] == "snippet,contentDetails,status"
    assert q2["id"] == "AAAAAAAAAA1,BBBBBBBBBB2,CCCCCCCCCC3,DDDDDDDDDD4,EEEEEEEEEE5"   # channel hit dropped
    assert h1 == {}


def test_search_candidates_filtered_ordered_and_attributed():
    p = provider(FakeHttp(SEARCH, VIDEOS))
    got = p.search("time lapse city", limit=2)
    assert [c.id for c in got] == ["youtube_cc:AAAAAAAAAA1", "youtube_cc:EEEEEEEEEE5"]   # relevance order kept
    a, e = got
    assert isinstance(a, Candidate) and a.provider == "youtube_cc" and a.kind == "video"
    assert a.duration == 65.0 and a.cost_usd == 0.0 and a.license == "cc-by-3.0" and a.creator == "Urban Lens"
    assert a.url == a.source_page == "https://www.youtube.com/watch?v=AAAAAAAAAA1"
    assert a.thumb.endswith("/AAAAAAAAAA1/maxresdefault.jpg")
    assert a.attribution.startswith('"City time lapse" by Urban Lens via YouTube (https://www.youtube.com/watch?v=')
    assert "CC BY 3.0" in a.attribution and "modified" in a.attribution
    assert (a.w, a.h) == (1280, 720) and (e.w, e.h) == (640, 360)     # definition lower bounds
    assert a.extra["video_id"] == "AAAAAAAAAA1" and a.extra["size_verified"] is False
    assert a.tags == ("city", "timelapse")
    assert p.quota_used == 101                                         # stopped after the 'short' pass


def test_titles_are_html_unescaped():
    vids = {"items": [_video("AAAAAAAAAA1", "Rock &amp; Roll&#39;s city", "A &amp; B", "PT20S")]}
    (c,) = provider(FakeHttp({"items": [{"id": {"videoId": "AAAAAAAAAA1"}}]}, vids)).search("q", limit=1)
    assert c.title == "Rock & Roll's city" and c.attribution.startswith('"Rock & Roll\'s city" by A & B')


def test_search_second_pass_and_dedupe():
    http = FakeHttp(SEARCH, VIDEOS, {"items": [{"id": {"videoId": "AAAAAAAAAA1"}}]})
    got = provider(http).search("time lapse city", limit=5)
    assert len(got) == 2 and [c[0] for c in http.calls] == ["search", "videos", "search"]
    assert http.calls[2][1]["videoDuration"] == "medium"


def test_search_is_deterministic_for_same_response():
    a = provider(FakeHttp(SEARCH, VIDEOS)).search("q", limit=2)
    b = provider(FakeHttp(SEARCH, VIDEOS)).search("q", limit=2)
    assert a == b and [c.to_dict() for c in a] == [Candidate.from_dict(c.to_dict()).to_dict() for c in b]


def test_images_and_blank_queries_cost_nothing():
    http = FakeHttp()
    p = provider(http)
    assert p.search("city", kind="image") == [] and p.search("  ") == []
    assert http.calls == [] and p.quota_used == 0


def test_unavailable_without_credentials_reports_founder_setup():
    http = FakeHttp()
    p = yt.YouTubeCC.from_settings({}, env={}, http=http, run=FakeRun())
    assert not p.available and p.download is False
    st = p.status()
    assert st["available"] is False and st["provider"] == "youtube_cc" and st["tos_warning"] is None
    assert "api-keys create" in st["setup"] and "youtube.googleapis.com" in st["setup"]
    assert p.search("city") == [] and http.calls == []


def test_scope_error_and_quota_error_keep_key_out_of_messages():
    with pytest.raises(yt.YouTubeAuthError, match="insufficient authentication scopes") as e:
        provider(FakeHttp(Err(403, SCOPE_403))).search("city")
    assert "test-key" not in str(e.value) and "api-keys create" in str(e.value)
    with pytest.raises(yt.YouTubeQuotaError) as e:
        provider(FakeHttp(Err(403, QUOTA_403))).search("city")
    assert "test-key" not in str(e.value)
    with pytest.raises(ProviderError):                                 # 5xx after base.Http's retries
        provider(FakeHttp(Err(503, {"error": "busy"}))).search("city")


def test_adc_mode_uses_bearer_token_and_quota_project():
    http, run = FakeHttp(SEARCH, VIDEOS), FakeRun(token="ya29.fake")
    p = provider(http, run, key=None, auth="adc", quota_project="demo-yt-project")
    assert p.available
    p.search("city", limit=1)
    _, q, h = http.calls[0]
    assert "key" not in q
    assert h == {"Authorization": "Bearer ya29.fake", "x-goog-user-project": "demo-yt-project"}
    assert run.calls[0] == ["gcloud", "auth", "application-default", "print-access-token"]


def test_settings_and_env_opt_in():
    s = {"media": {"youtube_download": True, "youtube_cc_key": "k1"}}
    p = yt.YouTubeCC.from_settings(s, env={})
    assert p.download and p.key == "k1" and p.status()["tos_warning"] == yt.TOS_WARNING
    p = yt.YouTubeCC.from_settings(s, env={"REEL_DIRECTOR_YOUTUBE_DOWNLOAD": "0", "YOUTUBE_API_KEY": "k2"})
    assert not p.download and p.key == "k2"
    assert yt.YouTubeCC.from_settings({"media": {"youtube_api_key": "k3"}}, env={}).key == "k3"
    assert yt.YouTubeCC.from_settings({"media": {"youtube_download": "false"}}, env={}).download is False
    assert yt.provider(None, env={"REEL_DIRECTOR_YOUTUBE_DOWNLOAD": "1"}).download is True
    adc = yt.provider({"media": {"youtube_auth": "adc"}}, env={})
    assert adc.available and adc.quota_project is None


def test_resolve_is_offline_unless_download_opted_in(tmp_path):
    (c,) = provider(FakeHttp(SEARCH, VIDEOS)).search("q", limit=1)
    run = FakeRun()
    off = provider(run=run, tmp=tmp_path).resolve(c)
    assert run.calls == [] and "youtube_download: false" in off.extra["rejected"]     # select.pick drops it
    assert "rejected" not in c.extra and (off.id, off.url, off.w) == (c.id, c.url, c.w)  # input untouched
    r = provider(run=run, tmp=tmp_path, download=True).resolve(c)
    assert (r.w, r.h) == (1920, 1080) and r.extra["source_w"] == 3840 and r.extra["license_verified"] is True
    assert r.license == "cc-by-3.0" and r.duration == 635.0 and r.extra["video_id"] == "AAAAAAAAAA1"
    assert "rejected" not in r.extra
    bad = provider(run=FakeRun(meta=dict(YTDLP_META, license=None)), download=True).resolve(c)
    assert bad.license == "unknown" and bad.extra["license_verified"] is False and "not CC BY" in bad.extra["rejected"]


def test_fetch_refused_by_default_with_tos_warning(tmp_path):
    run = FakeRun()
    p = provider(run=run, tmp=tmp_path)
    with pytest.raises(yt.YouTubeDownloadDisabled, match="Terms of Service"):
        p.fetch("aqz-KE-bpKQ")
    assert isinstance(yt.YouTubeDownloadDisabled("x"), ProviderError)   # resolver falls through to next source
    assert run.calls == [] and not any(tmp_path.iterdir())


def test_fetch_rejects_non_cc_by_before_downloading(tmp_path):
    for lic in (None, "Standard YouTube License", "CC BY-NC 4.0"):
        run = FakeRun(meta=dict(YTDLP_META, license=lic))
        with pytest.raises(yt.YouTubeLicenseError):
            provider(run=run, tmp=tmp_path, download=True).fetch("aqz-KE-bpKQ")
        assert run.downloads == []


@pytest.mark.parametrize("bad", ["--exec=rm", "youtube_cc:../../etc", "short", "aqz-KE-bpKQ;rm"])
def test_fetch_rejects_unsafe_ids(tmp_path, bad):
    run = FakeRun()
    with pytest.raises(yt.YouTubeError, match="invalid YouTube video id"):
        provider(run=run, tmp=tmp_path, download=True).fetch(bad)
    assert run.calls == []


def test_fetch_downloads_then_trims_into_content_addressed_cache(tmp_path, capsys):
    run = FakeRun()
    p = provider(run=run, tmp=tmp_path, download=True)
    cand = Candidate(id="youtube_cc:aqz-KE-bpKQ", provider="youtube_cc", kind="video", title="t", url="")
    path = p.fetch(cand, segment=(10, 14), max_height=360)
    assert "Terms of Service" in capsys.readouterr().err
    meta_cmd, dl, trim = run.calls
    assert meta_cmd[:5] == ["yt-dlp", "--ignore-config", "--no-playlist", "--no-update", "--no-progress"]
    assert "-J" in meta_cmd and "--skip-download" in meta_cmd
    assert "--download-sections" not in dl          # ffmpeg-streamed sections got 403 from YouTube
    fmt = dl[dl.index("-f") + 1]
    assert "height<=360" in fmt and "+ba" not in fmt                      # video-only B-roll by default
    assert dl[-2:] == ["--", "https://www.youtube.com/watch?v=aqz-KE-bpKQ"]
    assert trim[trim.index("-ss") + 1] == "10.000" and trim[trim.index("-t") + 1] == "4.000"
    assert "-an" in trim and "+bitexact" in trim and trim[trim.index("-c:v") + 1] == "libx264"
    body = b"fake-mp4-bytes|10.000+4.000"
    sha = hashlib.sha256(body).hexdigest()
    assert path == tmp_path / "files" / sha[:2] / f"{sha}.mp4" and path.read_bytes() == body
    side = json.loads(path.with_suffix(".json").read_text())
    assert side["license"] == "cc-by-3.0" and side["creator"] == "Blender" and side["segment"] == [10.0, 14.0]
    assert side["attribution"].startswith('"Big Buck Bunny') and "by Blender via YouTube" in side["attribution"]
    assert side["id"] == "youtube_cc:aqz-KE-bpKQ" and side["tos_warning"] == yt.TOS_WARNING
    logs = (tmp_path / "logs" / "youtube_downloads.jsonl").read_text().splitlines()
    assert len(logs) == 1 and json.loads(logs[0])["tos_acknowledged"] is True
    assert json.loads(logs[0])["status"] == "ok" and json.loads(logs[0])["sha256"] == sha
    assert not any((tmp_path / "tmp").iterdir())                                 # temp dir cleaned
    assert side["keys"] == ["youtube_cc:aqz-KE-bpKQ#10.000-14.000@360"] and side["sha256"] == sha
    # same request again -> cache hit, no yt-dlp/ffmpeg call, same path (deterministic)
    assert p.fetch("youtube_cc:aqz-KE-bpKQ", segment=(10.0, 14.0), max_height=360) == path
    assert len(run.calls) == 3


def test_fetch_whole_video_with_audio_skips_trim(tmp_path):
    run = FakeRun()
    path = provider(run=run, tmp=tmp_path, download=True).fetch(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ", with_audio=True)
    fmt = run.downloads[0][run.downloads[0].index("-f") + 1]
    assert fmt.count("+ba") == 3 and run.trims == [] and path.read_bytes() == b"fake-mp4-bytes"


def test_fetch_refuses_overlong_sources_and_bad_segments(tmp_path):
    run = FakeRun(meta=dict(YTDLP_META, duration=3600))
    with pytest.raises(yt.YouTubeError, match="pick a shorter source"):
        provider(run=run, tmp=tmp_path, download=True).fetch("aqz-KE-bpKQ", segment=(1, 3))
    assert run.downloads == []
    with pytest.raises(yt.YouTubeError, match="invalid segment"):
        provider(tmp=tmp_path, download=True).fetch("aqz-KE-bpKQ", segment=(5, 2))


def test_failed_download_is_logged_with_update_hint(tmp_path):
    # what yt-dlp 2026.06.09 printed for the real proof attempt on 2026-10-20
    run = FakeRun(fail="ERROR: unable to download video data: HTTP Error 403: Forbidden")
    with pytest.raises(yt.YouTubeError, match="brew upgrade yt-dlp"):
        provider(run=run, tmp=tmp_path, download=True).fetch("aqz-KE-bpKQ", segment=(60, 64), max_height=240)
    (line,) = (tmp_path / "logs" / "youtube_downloads.jsonl").read_text().splitlines()
    rec = json.loads(line)
    assert rec["status"] == "failed" and rec["video_id"] == "aqz-KE-bpKQ" and "403" in rec["error"]
    assert not (tmp_path / "files").exists() and not (tmp_path / "index").exists() and run.trims == []


def test_video_id_from_candidate_url():
    c = Candidate(id="other-id", provider="youtube_cc", kind="video", title="t",
                  url="https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=3")
    assert yt.video_id(c) == "aqz-KE-bpKQ"
