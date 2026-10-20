"""v4 media B-roll, free-stock team: the fixes the 2026-10-20 live smoke tests asked for (no network; loopback only).

Archive: uploader-declared licenses are not trusted (a Pingu/Nickelodeon rip marked PDM was the top "clock" hit,
"Taxi Driver 1976" sat in feature_films as CC BY 4.0), so only curated collections are searched unless the creator
opts in. Commons: a standard-width rendition instead of an 8 MB original; no hidden Wikidata labels in credits.
NASA: ISS crew photos with a burned-in frame-id strip are flagged. Http: a timeout is not retried and trips a
per-run breaker (Openverse search hung 30-60 s per call); chunked bodies are read without their framing.
"""
import http.server
import json
import threading
import urllib.error
import urllib.parse

import pytest

from reel_director.media import select as S
from reel_director.media.base import Candidate, Http, ProviderError, ProviderTimeout, clean_text
from reel_director.media.providers import archive, nasa, openverse, wikimedia
from test_media_free import FakeHttp, fx


# --- Internet Archive: curated collections by default -----------------------------------------------------------

def test_archive_search_query_and_resolve():
    meta = fx("archive_metadata_conquer.json")          # + a broadcast master, as NASA's Archive items carry
    meta["files"].append({"name": "Conquerb1943.mxf", "format": "MPEG2", "width": "1920", "height": "1080",
                          "length": "640.4", "size": "3663093968", "source": "original"})
    http = FakeHttp([("advancedsearch", fx("archive_search_clock_curated.json")), ("metadata/Conquer", meta)])
    p = archive.provider(None, http=http)
    got = p.search('clock* "AND" (x)', "video")
    q = urllib.parse.unquote_plus(http.calls[0][0])
    assert "title:(clock x)" in q and "licenseurl:(" in q and "*" not in q.split("licenseurl")[1]
    assert "collection:(prelinger OR fedflix OR nasa)" in q                  # curated collections only (default)
    assert [(c.id, c.license, c.extra["license_trust"]) for c in got] == [
        ("archive:Conquerb1943", "pd", "curated"), ("archive:MercuryGeminiApolloHdResourceReel", "pdm-1.0", "curated")]
    r = p.resolve(got[0])
    assert r.url == "https://archive.org/download/Conquerb1943/Conquerb1943.mp4" and (r.w, r.h) == (640, 480)
    assert r.duration == 640.47 and r.extra["format"] == "h.264" and len(r.extra["frames"]) == 6
    assert p.search("clock", "image") == []


def test_archive_uploader_declared_items_are_dropped_unless_opted_in(monkeypatch):
    monkeypatch.delenv("REEL_DIRECTOR_ARCHIVE_ANY_UPLOADER", raising=False)
    routes = [("advancedsearch", fx("archive_search_clock.json")), ("metadata/seat", fx("archive_metadata_seat.json"))]
    assert archive.provider(None, http=FakeHttp(routes)).search("clock", "video") == []   # none is in a curated set
    http = FakeHttp(routes)
    p = archive.provider({"media": {"archive_any_uploader": True}}, http=http)
    got = p.search("clock", "video")
    assert "collection:(" not in urllib.parse.unquote_plus(http.calls[0][0]) and len(got) == 4
    assert all(c.extra["license_trust"] == "uploader-declared" for c in got)
    assert all("verify the rights holder" in c.extra["license_note"] for c in got)
    seat = p.resolve(next(c for c in got if c.id == "archive:seat_20260723"))
    assert seat.url.endswith("/seat_20260723/seat.mp4") and (seat.w, seat.h, seat.duration) == (640, 360, 81.05)
    trusted = Candidate.from_dict({**seat.to_dict(), "extra": {**seat.extra, "license_trust": "curated"}})
    assert S.score(seat, "clock").score == pytest.approx(0.8 * S.score(trusted, "clock").score)
    assert not archive.provider({"media": {"archive_any_uploader": "no"}}).any_uploader
    monkeypatch.setenv("REEL_DIRECTOR_ARCHIVE_ANY_UPLOADER", "1")
    assert archive.provider(None).any_uploader


# --- Wikimedia Commons: renditions and clean credits -------------------------------------------------------------

def test_commons_images_fetch_a_standard_width_rendition():
    t = "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/123px-x.jpg/500px-123px-x.jpg"
    assert wikimedia.scaled(t, 3378, 4622, 1080, "portrait") == (t.replace("/500px-123", "/1920px-123"), 1920, 2627)
    assert wikimedia.scaled(t, 4000, 3000, 1080, "landscape")[1:] == (3840, 2880)
    assert wikimedia.scaled(t, 1500, 2000, 1080, "portrait") is None             # only the original is big enough
    assert wikimedia.scaled(t, 3000, 2000, 1080) is None and wikimedia.scaled(t, 6000, 4000, 1080)[1:] == (3840, 2560)
    tif = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Scan.tif/lossy-page1-500px-Scan.tif.jpg"
    assert wikimedia.scaled(tif, 6000, 8000, 1080, "portrait")[0].endswith("/lossy-page1-1920px-Scan.tif.jpg")
    assert wikimedia.scaled("https://upload.wikimedia.org/wikipedia/commons/a/ab/x.jpg", 6000, 8000, 1080) is None


def test_commons_credits_drop_hidden_wikidata_labels():
    pages = fx("wikimedia_image_clock.json")["query"]["pages"]
    el = next(pg for pg in pages if "Elephant" in pg["title"])
    c = wikimedia.provider(None, http=FakeHttp()).candidate(el, "image", 1080, (2.0, 10.0), "portrait")
    assert "QS:" not in c.title + c.attribution and c.title.startswith('"The Elephant Clock", Folio')
    assert clean_text('<i>A</i><div style="display: none;">label QS:Len,"A"</div> b') == "A b"


# --- NASA: burned-in frame strips ------------------------------------------------------------------------------

def test_nasa_iss_frame_strip_is_flagged_and_ranked_lower():
    got = nasa.provider(None, http=FakeHttp([("images-api", fx("nasa_image_laptop.json"))])).search(
        "laptop", "image", orientation="portrait")
    assert got and all(c.extra["text_overlay"] for c in got)                 # iss029e007212, iss002e7599...
    clean = Candidate.from_dict({**got[0].to_dict(), "extra": {k: v for k, v in got[0].extra.items()
                                                               if k != "text_overlay"}})
    assert S.quality(got[0]) == pytest.approx(0.7 * S.quality(clean))
    assert nasa.FRAME_STRIP.match("s135e012345") and not nasa.FRAME_STRIP.match("GSFC_20080520_HST")


# --- Http seam: timeouts and chunked bodies -------------------------------------------------------------------

def test_timeout_is_not_retried_and_trips_the_breaker(monkeypatch):
    calls = []

    def hang(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.URLError(TimeoutError("The read operation timed out"))
    monkeypatch.setattr("urllib.request.urlopen", hang)
    h = Http(retries=2, backoff=0)
    with pytest.raises(ProviderTimeout):
        h.get_json("https://api.openverse.org/v1/images/?q=clock")
    assert len(calls) == 1                                                  # not 3 x 30 s
    p = openverse.provider(None, http=h)
    with pytest.raises(ProviderTimeout):
        p.search("clock")
    with pytest.raises(ProviderTimeout, match="skipped"):
        p.search("laptop")
    assert len(calls) == 2                                                  # the breaker kept it off the network
    cands, notes = S.gather({"openverse": p}, ["openverse"], "camera", "image")
    assert cands == [] and notes[0].startswith("openverse: ProviderTimeout")

    def refuse(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.URLError(ConnectionRefusedError("refused"))
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(ProviderError) as e:
        Http(retries=2, backoff=0).get_json("https://commons.wikimedia.org/w/api.php")
    assert not isinstance(e.value, ProviderTimeout) and len(calls) == 5     # other network errors still retry


class Chunked(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body = json.dumps({"ok": True, "pad": "x" * 70000}).encode()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(0, len(self.body), 4096):
            part = self.body[i:i + 4096]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
        self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *a):
        pass


def test_chunked_bodies_are_read_without_their_framing(monkeypatch, tmp_path):
    """Regression: r.read(-1) on a chunked response returns the raw stream, chunk sizes included."""
    for k in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Chunked)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/x"
        assert Http(retries=0).get_json(url) == json.loads(Chunked.body)
        Http(retries=0).download(url, tmp_path / "b.json")
        assert (tmp_path / "b.json").read_bytes() == Chunked.body
    finally:
        srv.shutdown()
        srv.server_close()
