"""stage.py: pack import closure, disk-lean linking, bundled OFL fonts, pack id lookups."""
import json
import os
import re

import pytest

from reel_director import stage

HAVE_PACK = (stage.pack_root() / "transitions" / "lib" / "tx-dom.js").exists()
needs_pack = pytest.mark.skipif(not HAVE_PACK, reason="motion-pack not installed")


def test_closure_follows_relative_imports_and_cycles(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "a.js").write_text("import { b } from './lib/b.js';\nexport const a = 1;\n")
    (tmp_path / "lib" / "b.js").write_text("import { a } from '../a.js';\nimport './c.js';\nexport { x } from './d.js';\n")
    (tmp_path / "lib" / "c.js").write_text("// side effects\n")
    (tmp_path / "lib" / "d.js").write_text("export const x = 2; // import('./never.js') is not static\n")
    assert stage.import_closure(tmp_path, ["a.js"]) == ["a.js", "lib/b.js", "lib/c.js", "lib/d.js"]


def test_missing_module_is_a_compile_error_with_its_path(tmp_path):
    (tmp_path / "a.js").write_text("import { z } from './gone.js';\n")
    with pytest.raises(stage.StageError, match="gone.js"):
        stage.import_closure(tmp_path, ["a.js"])


def test_import_outside_the_pack_is_refused(tmp_path):
    (tmp_path / "pack").mkdir()
    (tmp_path / "outside.js").write_text("")
    (tmp_path / "pack" / "a.js").write_text("import '../outside.js';\n")
    with pytest.raises(stage.StageError, match="outside the pack"):
        stage.import_closure(tmp_path / "pack", ["a.js"])


@needs_pack
def test_stage_links_pack_fonts_and_runtime_idempotently(tmp_path):
    info = stage.stage(tmp_path)
    assert "transitions/lib/tx-dom.js" in info["modules"] and "layers/grade.js" in info["modules"]
    for rel in info["modules"]:
        dest, src = tmp_path / "assets" / "mp" / rel, stage.pack_root() / rel
        assert dest.read_bytes() == src.read_bytes()
        if not dest.is_symlink():
            assert os.stat(dest).st_ino == os.stat(src).st_ino or dest.stat().st_size == src.stat().st_size
    css = (tmp_path / "assets" / "rd" / "reel.css").read_text()
    for url in re.findall(r'url\("\.\./fonts/([^"]+)"\)', css):
        assert (tmp_path / "assets" / "fonts" / url).is_file(), url
    assert (tmp_path / "assets" / "rd" / "reel.mjs").read_text().startswith("/* Reel Director")
    stage.stage(tmp_path)                           # second run replaces, never fails on existing links
    assert (tmp_path / "assets" / "mp" / "transitions" / "lib" / "tx-dom.js").exists()


def test_runtime_is_seek_safe_and_has_no_css_animation():
    strip = lambda s: re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", s, flags=re.S))   # code only, not comments
    js, css = strip((stage.WEB / "reel.mjs").read_text()), strip((stage.WEB / "reel.css").read_text())
    assert "Math.random" not in js and "Date." not in js and "new Date" not in js and "performance.now" not in js
    assert "transition:" not in css and "animation" not in css


def test_bundled_fonts_are_ofl_and_small():
    lic = json.loads((stage.FONTS / "LICENSES.json").read_text())
    families = {v["family"] for v in lic.values()}
    assert {"Montserrat", "Anton", "Bebas Neue", "Inter", "Bangers", "Instrument Serif", "Noto Sans Devanagari",
            "Archivo Black"} == families
    total = 0
    for pkg, v in lic.items():
        assert v["license"] == "OFL-1.1" and (stage.FONTS / pkg / "OFL.txt").is_file()
        for f in v["files"]:
            total += (stage.FONTS / pkg / f).stat().st_size
    assert total < 3_000_000


@needs_pack
def test_pack_ids_resolve():
    assert stage.resolve_sfx("snd.ui.pop").is_file()
    with pytest.raises(stage.StageError):
        stage.resolve_sfx("snd.nope")
    aliases, catalog = stage.transition_tables()
    assert aliases["whip"]["key"] == "whip" and catalog["whip"]["timing"]["ms"] > 0
