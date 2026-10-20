"""Studio HTTP server: the browser UI's API over a Studio runtime (see runtime.py).

Stdlib only (ThreadingHTTPServer), bound to 127.0.0.1, JSON everywhere.

  GET  /api/project                    script, shots, takes (+QA), best take, build status
  POST /api/takes?shot=&source=record|import&ext=mp4|webm|mov
                                       body = the file; X-Capture-Info = JSON, ASCII-only (escape
                                       non-ASCII or encodeURIComponent it), e.g.
                                       {"video": {"label", "settings"}, "audio": {"label", "settings"},
                                        "mime", "videoBitsPerSecond", "audioBitsPerSecond"}
  POST /api/takes/<name>/pin | unpin | discard
  POST /api/build, GET /api/build
  POST /api/preview                    preview edit: takes so far + RECORD slots -> renders/preview.mp4
                                       (same worker and status as /api/build; 409 while one runs)
  POST /api/preset?name=clean-pro      the build's style preset (studio-settings.json)
  POST /api/options?director=1&matte=0  build toggles: editing director review (+ fix rounds), background matte
  GET  /api/creator                     {"profile": qa/creator.json | null}: the framing coach's creator profile
  GET  /api/broll, /api/broll/file      the B-roll panel: media picks, licences, credits, spend (studio/broll.py)
  POST /api/broll/<slot>/swap|reject|restore|treatment|approve   the creator's B-roll decisions (next build)
  GET  /media/<path under the project>  takes and renders, with Range support
  GET  /, /static/<file>                the studio UI
"""
import json
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .project import UPLOAD_EXTS, Project, ProjectError
from .runtime import Studio

STATIC = Path(__file__).resolve().parent / "static"
MEDIA_DIRS = {"raw", "renders", "qa", "prepped"}
DISK_RESERVE = 1 << 30            # refuse uploads that would leave less than 1 GiB free
MAX_UPLOAD = 8 << 30
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",   # B-roll picks
         ".woff2": "font/woff2", ".wasm": "application/wasm", ".mp4": "video/mp4", ".webm": "video/webm",
         ".mov": "video/quicktime", ".wav": "audio/wav", ".log": "text/plain; charset=utf-8",
         ".txt": "text/plain; charset=utf-8"}


class RangeNotSatisfiable(ValueError):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """One `bytes=` range -> inclusive (start, end); None means send the whole file.
    Multi-range and malformed headers are ignored, as RFC 9110 allows."""
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header or "")
    if not m or not (m[1] or m[2]):
        return None
    if not m[1]:
        if int(m[2]) == 0 or size == 0:
            raise RangeNotSatisfiable
        return max(0, size - int(m[2])), size - 1
    start, end = int(m[1]), int(m[2]) if m[2] else size - 1
    if start >= size:
        raise RangeNotSatisfiable
    return (start, min(end, size - 1)) if end >= start else None


def safe_parts(raw: str) -> list[str] | None:
    """URL path tail -> decoded segments, or None if any segment could escape its folder."""
    parts = [unquote(p) for p in raw.split("/")]
    if not parts or any(p in ("", ".", "..") or p.startswith(".") or "/" in p or "\\" in p or "\x00" in p
                        for p in parts):
        return None
    return parts


def contained(base: Path, parts: list[str]) -> Path | None:
    """base/parts if it is a regular file that really lives under base (symlinks resolved)."""
    base = base.resolve()
    p = base.joinpath(*parts).resolve()
    return p if p.is_relative_to(base) and p.is_file() else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ReelStudio/1"

    @property
    def studio(self) -> Studio:
        return self.server.studio

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def log_request(self, code="-", size="-"):
        if self.command == "POST" or (isinstance(code, int) and code >= 400):
            super().log_request(code, size)

    # --- plumbing -------------------------------------------------------------------------
    def _origin_ok(self) -> bool:
        """Refuse DNS-rebinding Hosts and cross-site POSTs (another tab can't discard takes)."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        host = self.headers.get("Host")
        if host and host not in allowed:
            return False
        origin = self.headers.get("Origin")
        return self.command != "POST" or origin is None or origin in {f"http://{h}" for h in allowed}

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if not self._origin_ok():
                self.close_connection = True
                return self._json(403, {"error": "request refused: wrong Host or cross-site Origin"})
            if method in ("GET", "HEAD"):
                if path in ("/", "/index.html"):
                    return self._static(["index.html"])
                if path == "/favicon.ico" and not (STATIC / "favicon.ico").exists():
                    self.send_response(204)   # no icon shipped: keep the browser console free of 404s
                    self.end_headers()
                    return None
                if path == "/favicon.ico":
                    return self._static(["favicon.ico"])
                if path.startswith("/static/"):
                    return self._static(safe_parts(path[len("/static/"):]))
                if path.startswith("/media/"):
                    return self._media(safe_parts(path[len("/media/"):]))
                if path == "/api/project":
                    return self._json(200, self.studio.project_view())
                if path == "/api/build":
                    return self._json(200, self.studio.build_status())
                if path == "/api/creator":
                    return self._json(200, self.studio.creator())
                if path == "/api/broll":
                    return self._json(200, self.studio.broll.view())
                if path == "/api/broll/file":
                    return self._broll_file(parse_qs(url.query))
            elif method == "POST":
                if path == "/api/takes":
                    return self._upload(parse_qs(url.query))
                if m := re.fullmatch(r"/api/takes/([^/]+)/(pin|unpin|discard)", path):
                    return self._take_action(unquote(m[1]), m[2])
                if path == "/api/build":
                    return self._json(*self.studio.start_build())
                if path == "/api/preview":
                    return self._json(*self.studio.start_build(preview=True))
                if path == "/api/preset":
                    return self._json(*self.studio.set_preset((parse_qs(url.query).get("name") or [""])[0]))
                if path == "/api/options":
                    return self._json(*self.studio.set_options({k: v[0] for k, v in parse_qs(url.query).items()}))
                if m := re.fullmatch(r"/api/broll/([^/]+)/([a-z]+)", path):     # the B-roll panel's decisions
                    busy = self.studio.build_status()["state"] == "running"
                    return self._json(*self.studio.broll.act(unquote(m[1]), m[2], {k: v[0] for k, v in
                                                                                   parse_qs(url.query).items()}, busy))
            known = (path in ("/api/project", "/api/build", "/api/takes", "/api/preset", "/api/preview", "/api/options",
                              "/api/creator", "/api/broll", "/api/broll/file")
                     or path.startswith(("/api/takes/", "/api/broll/")))
            self.close_connection = True
            if known:
                return self._json(405, {"error": f"{method} {path} not supported"})
            return self._json(404, {"error": "not found"})
        except ProjectError as e:
            self.close_connection = True
            return self._json(404 if str(e).startswith("no take") else 400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:
            traceback.print_exc()
            self.close_connection = True
            try:
                self._json(500, {"error": f"{type(e).__name__}: {e}"})
            except OSError:
                pass

    # --- routes ---------------------------------------------------------------------------
    def _static(self, parts: list[str] | None) -> None:
        f = contained(STATIC, parts) if parts else None
        if f is None:
            msg = "studio UI not installed" if parts == ["index.html"] else "not found"
            return self._json(404, {"error": msg})
        self._file(f)

    def _media(self, parts: list[str] | None) -> None:
        f = contained(self.studio.project.root, parts) if parts and parts[0] in MEDIA_DIRS else None
        if f is None:
            return self._json(404, {"error": "not found"})
        self._file(f)

    def _broll_file(self, q: dict) -> None:
        """A B-roll pick's thumbnail / file: only a path media.json names, with a media suffix (studio/broll.py)."""
        try:
            i = int((q.get("i") or ["-1"])[0])
        except ValueError:
            i = -1
        f = self.studio.broll.file((q.get("slot") or [""])[0], i)
        return self._file(f) if f else self._json(404, {"error": "not found"})

    def _file(self, f: Path) -> None:
        """Serve a file; one byte range at a time so <video> can seek."""
        st = f.stat()
        size, etag = st.st_size, f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        modified = formatdate(st.st_mtime, usegmt=True)
        rng = self.headers.get("Range")
        if rng and self.headers.get("If-Range") not in (None, etag, modified):
            rng = None
        head = {"Accept-Ranges": "bytes", "ETag": etag, "Last-Modified": modified}
        ctype = TYPES.get(f.suffix.lower(), "application/octet-stream")
        try:
            span = parse_range(rng, size)
        except RangeNotSatisfiable:
            return self._send(416, b"", ctype, {**head, "Content-Range": f"bytes */{size}"})
        start, end = span or (0, size - 1)
        self.send_response(206 if span else 200)
        for k, v in {**head, "Content-Type": ctype, "Content-Length": str(max(0, end - start + 1)),
                     "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
            self.send_header(k, v)
        if span:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0 and (chunk := fh.read(min(1 << 18, left))):
                self.wfile.write(chunk)
                left -= len(chunk)

    def _body_chunks(self):
        """Request body in pieces: Content-Length or chunked transfer encoding."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            while (size := int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)) > 0:
                yield self.rfile.read(size)
                self.rfile.readline()
            while self.rfile.readline().strip():
                pass
            return
        left = int(self.headers.get("Content-Length") or 0)
        while left > 0:
            chunk = self.rfile.read(min(1 << 20, left))
            if not chunk:
                raise ConnectionResetError("upload interrupted")
            left -= len(chunk)
            yield chunk

    def _upload(self, q: dict) -> None:
        p = self.studio.project
        self.close_connection = True   # until the body has been read
        shot, source, ext = (q.get(k, [""])[0] for k in ("shot", "source", "ext"))
        p.check_shot(shot)
        if source not in ("record", "import"):
            raise ProjectError("source must be 'record' or 'import'")
        if ext.lower() not in UPLOAD_EXTS:
            raise ProjectError(f"ext must be one of {', '.join(UPLOAD_EXTS)}")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return self._json(413, {"error": "file too large"})
        if shutil.disk_usage(p.root).free - length < DISK_RESERVE:
            return self._json(507, {"error": "not enough free disk space for this take"})
        info = self._capture_info()
        name, dest = p.reserve(shot, ext.lower())
        received = 0
        try:
            with open(dest, "wb") as fh:
                for chunk in self._body_chunks():
                    fh.write(chunk)
                    received += len(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        self.close_connection = False
        if received == 0:
            dest.unlink()
            raise ProjectError("empty upload")
        meta = {"source": source, "ext": ext.lower(), "bytes": received, "received": time.time(), "client": info}
        p.capture_file(name).write_text(json.dumps(meta, indent=1))
        p.add(shot, name)
        self.studio.enqueue(name)
        self._json(201, {"name": name, "status": "checking"})

    def _capture_info(self):
        raw = self.headers.get("X-Capture-Info")
        if not raw:
            return None
        for text in (raw, unquote(raw)):
            try:
                return json.loads(text)
            except ValueError:
                continue
        return {"unparsed": raw[:2000]}

    def _take_action(self, name: str, action: str) -> None:
        p = self.studio.project
        if action == "discard":
            moved = p.discard(name)
            return self._json(200, {"name": name, "discarded": True, "moved": moved})
        p.set_pin(name, action == "pin")
        shot, take = p.find(name)
        self._json(200, {"name": name, "shot": shot, "pin": take["pin"]})


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, studio: Studio):
        super().__init__(addr, Handler)
        self.studio = studio


def _open_browser(url: str) -> None:
    """Chrome first: it is the browser the studio is built and tested for."""
    chrome = Path("/Applications/Google Chrome.app")
    if sys.platform == "darwin" and chrome.exists():
        subprocess.Popen(["open", "-a", str(chrome), url])
    else:
        import webbrowser
        webbrowser.open(url)


def serve(script: Path, project_dir: Path, port: int = 8765, open_browser: bool = True) -> int:
    project = Project(project_dir, script)
    studio = Studio(project)
    try:
        httpd = StudioServer(("127.0.0.1", port), studio)
    except OSError as e:
        raise ProjectError(f"can't listen on 127.0.0.1:{port} ({e.strerror}); pass --port") from None
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    studio.start()

    def _term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    print(f"Reel Director studio: {url}\n  script  {project.script_path}\n  project {project.root}\n  Ctrl-C to stop",
          flush=True)
    if open_browser:
        _open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        studio.stop()
    return 0
