"""Studio B-roll panel (v4 contract): the build's media.json picks, with the creator's decisions.

  GET  /api/broll                         {items: [...], credits, spend, notes, stamp}: every media insert of the
                                          last plan, its pick (provider, license, attribution, thumb) and alternates
  GET  /api/broll/file?slot=&i=           a pick's local thumbnail or file (i = -1 the pick, 0.. an alternate)
  POST /api/broll/<slot>/swap?alt=<id>    use a free alternate
  POST /api/broll/<slot>/reject|restore   show the text card instead / take the pick back
  POST /api/broll/<slot>/treatment?name=  kenburns | parallax | sticker | device | polaroid | reveal | fullbleed | inset
  POST /api/broll/<slot>/approve?alt=<id> approve ONE paid generation (cost shown; per-reel and daily caps enforced)
Decisions take effect on the next build or preview (the compiler reads media.json; nothing is re-picked).
Nothing here spends money or downloads: approve() only records the approval, the next resolve generates.
"""
import re
from pathlib import Path

from .. import mediaplan

SLOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
ACTIONS = ("swap", "reject", "restore", "treatment", "approve")
SERVE = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}
YT_WARNING = ("YouTube's Terms of Service forbid downloading videos except through YouTube's own features, even "
              "Creative Commons ones. Reel Director downloads a CC-BY YouTube clip only when you turn on the local "
              "setting media.youtube_download, and it credits the creator.")


class Broll:
    def __init__(self, project):
        self.project = project

    @property
    def path(self) -> Path:
        return self.project.root / "media.json"

    def _thumb(self, slot: str, i: int, c: dict | None) -> str | None:
        if not c:
            return None
        t = str(c.get("thumb") or "")
        if t.startswith("https://"):
            return t
        return f"/api/broll/file?slot={slot}&i={i}" if self._local(c) else None

    @staticmethod
    def _local(c: dict) -> Path | None:
        for k in ("thumb", "path", "sticker"):
            v = c.get(k)
            if v and not str(v).startswith(("http://", "https://")):
                p = Path(v)
                if p.suffix.lower() in SERVE and p.is_file():
                    return p
        return None

    @staticmethod
    def _cand(c: dict | None) -> dict | None:
        if not c:
            return None
        keep = ("id", "provider", "kind", "title", "license", "attribution", "source_page", "w", "h", "duration",
                "cost_usd")
        return {k: c.get(k) for k in keep if c.get(k) is not None}

    def view(self) -> dict:
        doc = mediaplan.load(self.path)
        order = []
        try:
            order = [sh.id for sh in self.project.script().shots]
        except Exception:      # a broken script still shows the picks it had
            pass
        rank = {sid: k for k, sid in enumerate(order)}
        items = []
        for slot, it in sorted(doc["items"].items(), key=lambda kv: (rank.get(kv[1].get("shot"), 99), kv[0])):
            if it.get("stale"):
                continue
            alts = list(it.get("alternates") or [])
            items.append({
                "slot": slot, "shot": it.get("shot"), "at": it.get("at"), "query": it.get("query"),
                "media": it.get("media"), "treatment": it.get("treatment"), "layout": it.get("layout"),
                "status": it.get("status"), "paid_ok": bool(it.get("paid_ok")), "notes": it.get("notes") or [],
                "chosen": {**(self._cand(it.get("chosen")) or {}), "thumb": self._thumb(slot, -1, it.get("chosen"))}
                if it.get("chosen") else None,
                "alternates": [{**self._cand(a), "thumb": self._thumb(slot, k, a)} for k, a in enumerate(alts) if a],
                "approved": it.get("approved")})
        yt = any((c or {}).get("provider") == "youtube_cc" for it in doc["items"].values()
                 for c in [it.get("chosen")] + list(it.get("alternates") or []))
        stamp = int(self.path.stat().st_mtime_ns) if self.path.exists() else 0
        return {"items": items, "credits": doc.get("credits") or mediaplan.credits(doc), "spend": mediaplan.spend(doc),
                "treatments": list(_treatments()), "youtube_warning": YT_WARNING if yt else None, "stamp": stamp,
                "note": None if self.path.exists() else "No B-roll picked yet: build or preview once to plan it."}

    def file(self, slot: str, i: int) -> Path | None:
        if not SLOT.match(slot or ""):
            return None
        it = mediaplan.load(self.path)["items"].get(slot)
        if not it:
            return None
        pool = [it.get("chosen")] if i < 0 else list(it.get("alternates") or [])[i:i + 1]
        return self._local(pool[0]) if pool and pool[0] else None

    def act(self, slot: str, action: str, q: dict, busy: bool = False) -> tuple[int, dict]:
        if not SLOT.match(slot or "") or action not in ACTIONS:
            return 404, {"error": "unknown B-roll slot or action"}
        if busy:
            return 409, {"error": "a build is running: change the B-roll when it is done"}
        try:
            if action == "swap":
                item = mediaplan.swap(self.path, slot, q.get("alt", ""))
            elif action == "reject":
                item = mediaplan.reject(self.path, slot)
            elif action == "restore":
                item = mediaplan.restore(self.path, slot)
            elif action == "treatment":
                item = mediaplan.set_treatment(self.path, slot, q.get("name", ""))
            else:
                item = mediaplan.approve(self.path, slot, q.get("alt", ""))
        except mediaplan.MediaError as e:
            return 400, {"error": str(e)}
        return 200, {"slot": slot, "status": item.get("status"), "treatment": item.get("treatment"),
                     "next": "Build or preview again to see it in the reel."}

    def write_credits(self) -> list[str]:
        """renders/reel.credits.txt: the licences of the media the last reel build shows (its timeline.json)."""
        return mediaplan.write_credits(self.project.root)


def _treatments():
    from ..broll_media import TREATMENTS
    return TREATMENTS
