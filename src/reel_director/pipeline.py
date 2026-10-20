"""The v1 build path, shared by the CLI and Studio (integrator-owned).

    script.json (+ --preset) -> director.direct -> council policy -> directed.json
    -> media resolution (v4: B-roll picks + fetches -> media.json) -> build_timeline -> mixdown (mix/mix.wav)
    -> compile_project(..., mix=) (+ renders/reel.credits.txt) -> [hyperframes render] -> audio.deliver

Auto cues only ever land in directed.json, never in script.json. `--no-auto`, style.auto_off and
style.auto_skip_shots switch the director off for the reel or for single shots.
"""
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from . import policy
from .schema import Script, ScriptError, parse_script, script_to_dict


def load(path: str | Path, preset: str | None = None) -> Script:
    """script.json with --preset applied (default clean-pro) and the council's preset patch."""
    path = Path(path)
    data = json.loads(path.read_text())
    for raw in data.get("shots") or []:     # reproduced: the tokenizer drops Devanagari words silently
        dev = [w for w in str(raw.get("line", "")).split() if any("\u0900" <= ch <= "\u097f" for ch in w)]
        if dev:
            raise ScriptError(f"shot {raw.get('id')!r}: Devanagari words {' '.join(dev)!r} would be dropped from the "
                              "captions; write Hinglish in Roman script for now (Devanagari input is deferred)")
    return parse_script(policy.prepare(data, preset), base_dir=path.parent.resolve())


def skip_shots(script: Script) -> Script:
    """style.auto_skip_shots: [shot ids] -> those shots get no auto cues (Shot.meta auto: false)."""
    skip = set(script.style.get("auto_skip_shots") or [])
    if not skip:
        return script
    unknown = skip - {sh.id for sh in script.shots}
    if unknown:
        raise ScriptError(f"style.auto_skip_shots names unknown shot(s): {sorted(unknown)}")
    shots = [replace(sh, meta={**sh.meta, "auto": False}) if sh.id in skip else sh for sh in script.shots]
    return replace(script, shots=shots)


def direct(s: Script, takes: dict | None, no_auto: bool = False, notes: list | None = None) -> Script:
    """Director + council caps on real word times (when takes exist). Returns `s` unchanged when auto
    is off. An auto cue that cannot be placed is dropped and noted; manual cues are never changed."""
    from . import director
    from .timeline import build_timeline
    notes = notes if notes is not None else []
    if no_auto or s.style.get("auto_off"):
        notes.append("director off (--no-auto or style.auto_off)")
        return s
    s = skip_shots(s)
    d = director.direct(s, build_timeline(s, takes or {}), notes)
    return policy.enforce(d, build_timeline(d, takes or {}), notes)


def write_directed(d: Script, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(script_to_dict(d), indent=1, ensure_ascii=False) + "\n")
    return path


def build(script: str | Path, out: str | Path, takes: dict | None = None, preset: str | None = None,
          no_auto: bool = False, mix: bool = True, directed_path: str | Path | None = None) -> dict:
    """Direct, time, mix and compile one reel. The mix goes to <out>/../mix/mix.wav (never inside the
    HyperFrames project: the compiler links it in). Returns what the CLI prints and Studio shows."""
    from . import mixdown
    from .compiler import compile_project
    from .timeline import build_timeline
    out = Path(out)
    s = load(script, preset)
    unknown = set(takes or {}) - {sh.id for sh in s.shots}
    if unknown:
        raise ScriptError(f"takes for unknown shot(s): {sorted(unknown)}")
    notes: list[str] = []
    d = direct(s, takes, no_auto, notes)
    dpath = write_directed(d, directed_path or out.parent / "directed.json")
    media = resolve_media(d, out, notes)
    tl = build_timeline(d, takes or {})
    mix_wav, rep = None, None
    if mix and any(p.take for p in tl.shots):
        mix_wav = out.parent / "mix" / "mix.wav"
        rep = mixdown.mixdown(tl, mix_wav)
    index = compile_project(tl, out, mix=mix_wav)
    try:     # the compiler's own notes: transitions downgraded to hard cuts, punches off (resolution guard)
        notes += [f"compile: {n}" for n in json.loads((out / "timeline.json").read_text()).get("notes", [])]
    except (OSError, ValueError):
        pass
    from .mediaplan import write_credits
    return {"timeline": tl, "directed": d, "directed_path": dpath, "index": index, "mix": mix_wav,
            "mix_report": rep, "notes": notes, "metrics": policy.metrics(d, tl), "media": media,
            "credits": write_credits(out.parent, out / "timeline.json"),
            "preset": s.style.get("preset"), "beta": s.style.get("preset") in policy.BETA_PRESETS}


def resolve_media(d: Script, out: str | Path, notes: list) -> Path | None:
    """Plan-time B-roll (v4): pick + fetch the director's media inserts into media.json before anything renders
    (mediaplan.media_path: the Studio project root, else next to directed.json). The creator's decisions in it are
    kept, so the same media.json builds the same reel. RD_MEDIA_OFFLINE=1 = no network: unresolved inserts show
    the text card they replaced. A failure here never sinks the build."""
    from . import mediaplan
    path = mediaplan.media_path(out)
    if not mediaplan.media_cues(d) and not path.exists():
        return None
    try:
        mediaplan.resolve(d, path, notes=notes)
    except Exception as e:      # noqa: BLE001 - a provider bug must not stop the reel: the label cards show
        notes.append(f"media: resolution failed ({type(e).__name__}: {e}); the text cards show")
    return path


# ---- after the render: QA gates, before/after, the editing director and its fix rounds (contract v2) ----
MIN_FREE = 3 << 30          # council 11: >= 3 GB free before each render
RENDER_ARGS = ["--quality", "delivery"]


def render(reel: str | Path, out_mp4: str | Path, log=print) -> Path:
    """hyperframes render <reel> -o <out_mp4> at delivery quality (the Studio streams the same command)."""
    hf = shutil.which("hyperframes")
    if not hf:
        raise RuntimeError("hyperframes CLI not found on PATH")
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out_mp4.parent).free < MIN_FREE:
        raise RuntimeError("less than 3 GB free on disk: render refused (council 11)")
    r = subprocess.run([hf, "render", str(reel), "-o", str(out_mp4), *RENDER_ARGS], capture_output=True, text=True,
                       env={**os.environ, "NO_COLOR": "1"})
    if r.returncode != 0 or not out_mp4.exists():
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        raise RuntimeError(f"render failed: {' | '.join(tail)}")
    log(f"  rendered {out_mp4}")
    return out_mp4


def _round_dir(build: Path, n: int, directed: dict) -> Path:
    """A fix round's own build dir (build/director/round-N): directed.json + build-takes.json re-rooted, so QA
    and the before/after sheet find the same raw takes. Nothing of the first build is overwritten."""
    rd = build / "director" / f"round-{n}"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "directed.json").write_text(json.dumps(directed, indent=1, ensure_ascii=False) + "\n")
    bt = build / "build-takes.json"
    if bt.exists():
        data = {sid: [{**t, "src": os.path.relpath(build / t["src"], rd)} for t in v]
                for sid, v in json.loads(bt.read_text()).items()}
        (rd / "build-takes.json").write_text(json.dumps(data, indent=2))
    return rd


def _promote(src: Path, build: Path) -> None:
    """The better round's master, QA report and sheets replace the build's own (file copies, never a dir delete)."""
    for rel in ("renders/reel-master.mp4", "renders/before-after.png", "renders/before-after.json",
                "qa/report.json", "qa/overlay.png", "qa/director.json"):
        if (src / rel).exists():
            (build / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, build / rel)


def review_build(build: str | Path, takes: dict | None = None, director: bool = False, director_json=None,
                 rounds: int = 0, log=print, timeout: float | None = None) -> dict:
    """QA gates + before/after on <build> (reel/, directed.json, renders/reel-master.mp4), then the optional
    editing director. With rounds (<= 2) and takes, failing-gate fixes + high/medium director fixes are
    applied to a copy of directed.json, re-compiled, re-rendered, delivered and re-reviewed in
    build/director/round-N; a round that scores better is promoted, the loop stops when it does not."""
    from . import review as rv
    from .audio import deliver
    from .qa import run_qa
    build = Path(build)
    shots = [s["id"] for s in json.loads((build / "reel" / "timeline.json").read_text())["shots"]]

    def ask(where: Path, rep: dict) -> dict | None:
        if director_json and where == build:     # a saved answer reviewed the first build only
            return {**rv.validate(json.loads(Path(director_json).read_text())), "source": str(director_json)}
        return rv.run_director(where, rep, shots, timeout=timeout or rv.TIMEOUT) if director else None

    def qa(where: Path) -> dict:
        rep = run_qa(where, where)
        d = ask(where, rep)
        rep = rv.with_director(rep, d)
        (where / "qa" / "report.json").write_text(json.dumps(rep, indent=1))
        if d is not None:
            (where / "qa" / "director.json").write_text(json.dumps(d, indent=1))
        return rep
    rep = qa(build)
    log(f"  qa: score {rep['score']} (gates {rep['gate_score']}), verdict {rep['verdict']}")
    cur, hist, best = json.loads((build / "directed.json").read_text()), [], None
    for n in range(1, max(0, min(int(rounds), 2)) + 1):
        if not takes:
            hist.append({"round": n, "stopped": "no takes: nothing to rebuild"})
            break
        d = rep.get("director") or {}
        fixes = rv.gate_fixes(rep) + [i for i in d.get("issues", []) if i["severity"] in ("high", "medium")]
        new, applied, rejected, human = rv.apply_fixes(cur, fixes)
        if not applied:
            hist.append({"round": n, "stopped": "nothing applicable", "rejected": rejected, "needs_human": human})
            break
        rd = _round_dir(build, n, new)
        log(f"  director round {n}: {len(applied)} fix(es) applied -> {rd}")
        r = build_fn(rd / "directed.json", rd / "reel", takes, no_auto=True)
        render(r["index"].parent, rd / "renders" / "reel.mp4", log)
        dl = deliver(rd / "renders" / "reel.mp4", r["mix"], rd / "renders" / "reel-master.mp4")
        rep2 = qa(rd)
        hist.append({"round": n, "dir": str(rd.relative_to(build)), "applied": applied, "rejected": rejected,
                     "needs_human": human, "score_before": rep["score"], "score_after": rep2["score"],
                     "deliver": {k: dl.get(k) for k in ("lufs", "true_peak", "av_start_offset_ms", "ok")}})
        log(f"  director round {n}: score {rep['score']} -> {rep2['score']}, verdict {rep2['verdict']}")
        if not better(rep, rep2):
            hist[-1]["stopped"] = "score did not improve: kept the previous build"
            break
        cur, rep, best = new, rep2, rd
    if best is not None:
        _promote(best, build)
    rep = {**rep, "rounds": hist, "final": str(best.relative_to(build)) if best else "."}
    (build / "qa" / "report.json").write_text(json.dumps(rep, indent=1))
    return rep


def better(a: dict, b: dict) -> bool:
    """b beats a: on the overall score when the director reviewed both, else on the deterministic gates."""
    ok = lambda r: (r.get("director") or {}).get("status") == "ok"  # noqa: E731
    return b["score"] > a["score"] if ok(a) and ok(b) else b["gate_score"] > a["gate_score"]


def build_fn(script, out, takes, no_auto=False):
    """build() with the defaults a fix round needs (indirection keeps review_build testable)."""
    return build(script, out, takes, None, no_auto, True, None)
