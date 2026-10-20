"""Stage the static runtime into a compiled reel project (disk-lean).

<project>/assets/mp/...   motion-pack modules the runtime imports, plus their static-import closure
                          (hard link, else symlink, else copy; the pack is never written to)
<project>/assets/fonts/   the bundled OFL fonts (src/reel_director/fonts, hard linked)
<project>/assets/rd/      reel.mjs + reel.css (copied, ~20 KB)

The pack is found at $RD_PACK, else ~/Developer/motion-pack-public. A missing module is a compile
error with its path, never a silent render without transitions.
"""
import json
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
FONTS = HERE / "fonts"
ENTRIES = ("transitions/lib/tx-dom.js", "layers/grade.js", "layers/presets/grades.js")
_IMPORT = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s*['"](\.[^'"]+)['"]|^\s*import\s*['"](\.[^'"]+)['"]""", re.M)


class StageError(RuntimeError):
    pass


def pack_root() -> Path:
    return Path(os.environ.get("RD_PACK") or Path.home() / "Developer" / "motion-pack-public")


def import_closure(root: Path, entries=ENTRIES) -> list[str]:
    """Relative paths of every module reachable from `entries` through static relative imports."""
    seen: set[str] = set()
    todo = list(entries)
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        path = root / rel
        if not path.is_file():
            raise StageError(f"motion-pack module missing: {path}")
        seen.add(rel)
        for m in _IMPORT.finditer(path.read_text()):
            dep = (path.parent / (m.group(1) or m.group(2))).resolve()
            try:
                todo.append(dep.relative_to(root.resolve()).as_posix())
            except ValueError:
                raise StageError(f"{rel} imports outside the pack: {dep}") from None
    return sorted(seen)


def link(src: Path, dest: Path) -> None:
    """Idempotent: replace dest with a hard link to src (symlink, then copy, as fallbacks)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    for make in (os.link, os.symlink):
        try:
            make(src, dest)
            return
        except OSError:
            continue
    shutil.copy2(src, dest)


def stage(out: Path, pack: Path | None = None) -> dict:
    out = Path(out)
    pack = Path(pack or pack_root())
    mods = import_closure(pack)
    for rel in mods:
        link(pack / rel, out / "assets" / "mp" / rel)
    fonts = []
    for f in sorted(FONTS.rglob("*")):
        if f.is_file() and f.suffix in {".woff2", ".txt", ".json"}:
            rel = f.relative_to(FONTS)
            link(f, out / "assets" / "fonts" / rel)
            fonts.append(rel.as_posix())
    rd = out / "assets" / "rd"
    rd.mkdir(parents=True, exist_ok=True)
    for name in ("reel.mjs", "reel.css"):
        dest = rd / name
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        shutil.copy2(WEB / name, dest)
    return {"pack": str(pack), "modules": mods, "fonts": fonts}


@lru_cache(maxsize=4)
def _sfx_index(pack: str) -> dict:
    data = json.loads((Path(pack) / "sfx" / "manifest.json").read_text())
    return {s["id"]: s for s in data["sounds"]}


def resolve_sfx(sfx_id: str, pack: Path | None = None) -> Path:
    """Pack SFX id (sfx/manifest.json) -> file path."""
    pack = Path(pack or pack_root())
    entry = _sfx_index(str(pack)).get(sfx_id)
    if not entry:
        raise StageError(f"unknown sfx id {sfx_id!r} (see {pack / 'sfx' / 'manifest.json'})")
    path = pack / "sfx" / entry["file"]
    if not path.is_file():
        path = pack / entry["file"]
    if not path.is_file():
        raise StageError(f"sfx {sfx_id!r} file missing: {entry['file']}")
    return path


def transition_tables(pack: Path | None = None) -> tuple[dict, dict]:
    """(aliases, catalog-by-key) from the pack's transitions folder."""
    pack = Path(pack or pack_root())
    aliases = json.loads((pack / "transitions" / "aliases.json").read_text())["aliases"]
    cat = json.loads((pack / "transitions" / "catalog.json").read_text())["transitions"]
    return aliases, {t["key"]: t for t in cat}
