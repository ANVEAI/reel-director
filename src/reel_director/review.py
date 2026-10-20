"""Editing director (contract v2): an opt-in headless `claude -p` review of the before/after sheet, the QA overlay
and the QA / layout JSON against a strict rubric, with a JSON-schema'd answer
{"score","summary","issues":[{"severity","what","where_t","fix":{"op","args"}}]}.

apply_fixes() applies whitelisted ops only (move_caption, drop_cue, change_preset_param, reframe; retake goes to a
human) to a COPY of directed.json; director_loop() rebuilds at most 2 rounds and stops when the score does not
improve. Everything degrades gracefully: no CLI, a logged-out CLI, a timeout or an answer that fails the schema ->
{"status":"skipped","note":...}. Only local file paths and the QA numbers go to the CLI, whose only tool is Read.

Usage: python -m reel_director.review <build_dir> --out DIR [--director] [--director-json FILE] [--apply]
"""
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .presets import BACKGROUNDS, CAPTIONS, GRADES, PACES
from .qa import OPS, run_qa, score

TIMEOUT = 300
ZONES = ("below-chin", "above-head", "lower-band")
CUE_TYPES = ("punch", "broll", "cutaway", "sfx", "title", "emphasis", "overlay", "transition", "zoom")
PARAMS = {"caption": CAPTIONS, "background": BACKGROUNDS, "pace": PACES, "look.grade": GRADES,
          "look.grain": (0.0, 0.08), "look.vignette": (0.0, 0.18), "title_backdrop": ("auto", "solid", "blur"),
          "accent": "hex"}
SEVERITY = ("high", "medium", "low")
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["score", "summary", "issues"],
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "issues": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False, "required": ["severity", "what", "where_t", "fix"],
            "properties": {
                "severity": {"enum": list(SEVERITY)}, "what": {"type": "string"},
                "where_t": {"type": ["number", "null"]},
                "fix": {"type": "object", "required": ["op", "args"], "additionalProperties": False,
                        "properties": {"op": {"enum": list(OPS)}, "args": {"type": "object"}}}}}}}}
RUBRIC = """You are the editing director for a 9:16 talking-head short (Reels / Shorts / TikTok), 1080x1920.
Judge the EDITED reel the way a viewer on a phone would, using only what the files show. Read every file listed
below with the Read tool before answering (the PNGs are images: look at them).

Rubric. Start at 100 and deduct:
- Faces are sacred: a caption, title, card or sticker over the eyes, nose or mouth is HIGH severity (-25).
- Caption legibility: contrast against what is behind it, size, line breaks, stroke or plate (-5 to -15).
- Title legibility: a title over a busy background needs a solid or blurred backdrop (-5 to -15).
- Framing: eye line near 0.40 of the frame height, headroom, face size and centring (-5 to -15).
- B-roll and cards must look designed (motion, background, hierarchy), never a flat static slide (-5 to -15).
- Pace: visual changes every ~1.8-2.6 s with a varied rhythm, nothing metronomic or static too long (-5 to -10).
- Audio: master -14 LUFS +-0.5, true peak <= -1.5 dBTP; the cleaned voice must not be worse than raw (-5 to -15).
- Before vs after: the edited frames must be clearly better than the raw take at the same moment.
Score anchors: 90-100 ship as is; 75-89 small fixes; 50-74 problems a viewer notices; under 50 broken.
The deterministic QA gates in qa/report.json are measured facts: do not contradict their numbers, add what they
cannot see (taste, hierarchy, what looks cheap).

Each issue: severity high|medium|low; what = one concrete sentence citing what you saw; where_t = reel seconds or
null; fix = exactly one op from this whitelist (no other ops exist):
- move_caption {"zone": "below-chin"|"above-head"|"lower-band", "shots": [shot ids]}
- drop_cue {"shot": id, "type": "punch"|"broll"|"sfx"|"title"|"emphasis", "at": "<word the cue sits on>"}
- change_preset_param {"param": one of PARAMS, "value": ...}
- reframe {"shots": [shot ids], "eye_y": 0.37-0.43, "scale": 1.0-1.10}
- retake {"shot": id, "reason": "..."}
PARAMS: caption in CAPTIONS; background in BACKGROUNDS; pace in PACES; look.grade in GRADES; look.grain 0-0.08;
look.vignette 0-0.18; title_backdrop in auto|solid|blur; accent "#RRGGBB".
Shot ids: SHOTS. At most 12 issues, most severe first. Answer with the JSON object only."""


def build_prompt(out: Path, report: dict, shots: list[str]) -> str:
    files = [p for p in (out / "renders" / "before-after.png", out / "qa" / "overlay.png", out / "qa" / "report.json",
                         out / "qa" / "layout.estimated.json") if p.exists()]
    gates = "\n".join(f"- {g['id']}: {g['level']}: {g['message']}" for g in report.get("gates", []))
    r = (RUBRIC.replace("CAPTIONS", "|".join(CAPTIONS)).replace("BACKGROUNDS", "|".join(BACKGROUNDS))
         .replace("PACES", "|".join(PACES)).replace("GRADES", "|".join(GRADES)).replace("SHOTS", ", ".join(shots)))
    return (r + "\n\nFiles (read all):\n" + "\n".join(f"- {p}" for p in files)
            + f"\n\nDeterministic gates (score {report.get('gate_score')}):\n{gates}\n")


def cli_env() -> dict:
    """The user's own CLI login, not the host session that may have launched this process (a nested CLI
    inheriting a desktop/SDK child's session variables cannot refresh that host's OAuth)."""
    keep = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") and k not in keep) and k not in ("USE_STAGING_OAUTH", "USE_LOCAL_OAUTH")}


def _skip(note: str) -> dict:
    return {"status": "skipped", "note": note, "score": None, "issues": []}


def validate(obj) -> dict:
    """Schema check + normalisation of a director answer; ops outside the whitelist are dropped (and listed)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("score"), (int, float)) or not isinstance(obj.get("issues"), list):
        return _skip("director answer failed the schema")
    issues, dropped = [], []
    for i in obj["issues"][:12]:
        fx = i.get("fix") if isinstance(i, dict) else None
        if not isinstance(fx, dict) or fx.get("op") not in OPS or not isinstance(fx.get("args", {}), dict):
            dropped.append(i)
            continue
        wt = i.get("where_t")
        issues.append({"severity": i.get("severity") if i.get("severity") in SEVERITY else "medium",
                       "what": str(i.get("what", ""))[:400],
                       "where_t": round(float(wt), 2) if isinstance(wt, (int, float)) else None,
                       "fix": {"op": fx["op"], "args": fx.get("args") or {}}})
    return {"status": "ok", "score": int(max(0, min(100, round(obj["score"])))), "summary": str(obj.get("summary", ""))[:600],
            "issues": issues, "dropped": dropped}


def run_director(out: Path, report: dict, shots: list[str], claude: str | None = None, timeout: float = TIMEOUT,
                 model: str | None = None, runner=subprocess.run) -> dict:
    """One headless review. Never raises: any failure is a skipped review with a note."""
    exe = claude or shutil.which("claude")
    if not exe:
        return _skip("claude CLI not installed: director review skipped")
    cmd = [exe, "-p", build_prompt(Path(out), report, shots), "--output-format", "json",
           "--json-schema", json.dumps(SCHEMA), "--tools", "Read", "--allowedTools", "Read",
           "--permission-mode", "dontAsk", "--safe-mode", "--no-session-persistence", "--add-dir", str(Path(out).resolve())]
    cmd += ["--model", model] if model else []
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(out), env=cli_env(),
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return _skip(f"director timed out after {timeout:.0f} s")
    except OSError as e:
        return _skip(f"claude CLI failed to start: {e}")
    try:
        res = json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        return _skip(f"claude CLI gave no JSON (exit {r.returncode}): {(r.stderr or '')[:200]}")
    if res.get("is_error"):
        msg = str(res.get("result", ""))[:200]
        hint = " (run `claude auth login` once in a terminal)" if "authenticat" in msg.lower() else ""
        return _skip(f"claude CLI error: {msg}{hint}")
    obj = res.get("structured_output")
    if obj is None:
        m = re.search(r"\{.*\}", str(res.get("result", "")), re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            obj = None
    d = validate(obj)
    if d["status"] == "ok":
        d.update(source="claude-cli", cost_usd=res.get("total_cost_usd"), duration_ms=res.get("duration_ms"),
                 turns=res.get("num_turns"))
    return d


def with_director(report: dict, director: dict | None) -> dict:
    g, s, v = score(report["gates"], director)
    return {**report, "director": director, "gate_score": g, "score": s, "verdict": v}


# ------------------------------------------------------------------------------------------------ fixes
def _norm(w) -> str:
    return re.sub(r"[^\w]", "", str(w).lower())


def _param_ok(param: str, value) -> bool:
    spec = PARAMS[param]
    if spec == "hex":
        return isinstance(value, str) and bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", value))
    if isinstance(spec, tuple) and len(spec) == 2 and all(isinstance(x, float) for x in spec):
        return isinstance(value, (int, float)) and spec[0] <= value <= spec[1]
    return value in spec


def _plan(op: str, a: dict, d: dict, shots: dict) -> tuple[list[tuple], str | None]:
    """The field assignments one fix would make, as (field key, value, apply()) - or why it is refused."""
    ids = a.get("shots") or ([a["shot"]] if a.get("shot") else list(shots))
    ids = [ids] if isinstance(ids, str) else ids
    zones = a.get("zones") if isinstance(a.get("zones"), dict) else {i: a.get("zone") for i in ids}
    if op not in OPS:
        return [], "op not whitelisted"
    if op == "change_preset_param":
        p, v = a.get("param"), a.get("value")
        if p not in PARAMS or not _param_ok(p, v):
            return [], f"param/value not allowed: {p}={v!r}"
        *path, last = p.split(".")

        def put():
            tgt = d.setdefault("style", {})
            for k in path:
                tgt = tgt.setdefault(k, {})
            tgt[last] = v
        return [(f"style.{p}", v, put)], None
    if not zones or any(i not in shots for i in zones) or not ids or any(i not in shots for i in ids):
        return [], f"unknown shot in {sorted(zones) if a.get('zones') else ids}"
    if op == "move_caption":
        if any(z not in ZONES for z in zones.values()):
            return [], f"zone must be one of {ZONES}"
        return [(f"{i}.caption_zone", z, lambda i=i, z=z: shots[i].__setitem__("caption_zone", z))
                for i, z in zones.items()], None
    if op == "reframe":
        eye, sc = a.get("eye_y", 0.40), a.get("scale")
        if not isinstance(eye, (int, float)) or not 0.37 <= eye <= 0.43:
            return [], "eye_y must be 0.37-0.43"
        if sc is not None and (not isinstance(sc, (int, float)) or not 1.0 <= sc <= 1.10):
            return [], "scale must be 1.0-1.10"
        fields = [("eye_y", round(float(eye), 3))] + ([("scale", float(sc))] if sc is not None else [])
        return [(f"{i}.reframe.{k}", v, lambda i=i, k=k, v=v: shots[i].setdefault("reframe", {}).__setitem__(k, v))
                for i in ids for k, v in fields], None
    if op == "drop_cue":
        sh = shots.get(a.get("shot"))
        cue = next((c for c in (sh or {}).get("cues", []) if c.get("type") == a.get("type")
                    and _norm(c.get("at")) == _norm(a.get("at"))), None)
        if a.get("type") not in CUE_TYPES or sh is None or cue is None:
            return [], "no such cue"
        if not cue.get("auto"):
            return [], "manual cue: the creator's choice, never dropped automatically"
        return [(f"{sh['id']}.drop.{a['type']}.{_norm(a['at'])}", True, lambda: sh["cues"].remove(cue))], None
    return [], None                                        # retake: for a human


def apply_fixes(directed: dict, fixes: list[dict]) -> tuple[dict, list, list, list]:
    """Apply whitelisted ops (issue dicts with "fix", or bare {"op","args"}) to a deep copy of directed.json.
    Returns (new directed, applied, rejected [(fix, reason)], needs_human). Overrides land on the shot as
    "caption_zone" / "reframe" and in style (dotted params nest: look.grade -> style.look.grade). The first fix
    to set a field owns it: a later fix that sets it differently is refused, so pass measured gate fixes first."""
    d = copy.deepcopy(directed)
    shots = {s["id"]: s for s in d.get("shots", [])}
    applied, rejected, human, seen, owner = [], [], [], set(), {}
    for item in fixes:
        f = item.get("fix", item) if isinstance(item, dict) else {}
        op, a = f.get("op"), f.get("args") or {}
        key = json.dumps([op, a], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        sets, why = _plan(op, a, d, shots)
        clash = [k for k, v, _ in sets if k in owner and owner[k] != v]
        why = why or (f"conflicts with an earlier fix on {clash[0]}" if clash else None)
        if why:
            rejected.append((f, why))
        elif op == "retake":
            human.append({"shot": a.get("shot") or (a.get("shots") or [None])[0], "reason": a.get("reason", "")})
        else:
            for k, v, put in sets:
                owner[k] = v
                put()
            applied.append(f)
    return d, applied, rejected, human


def gate_fixes(report: dict) -> list[dict]:
    return [g["fix"] for g in report.get("gates", []) if g["level"] == "fail" and g.get("fix")]


def director_loop(directed: dict, report: dict, rebuild, review, max_rounds: int = 2) -> dict:
    """Bounded fix loop. review(report) -> director dict; rebuild(directed) -> new QA report (gates only).
    Each round applies failing-gate fixes + high/medium director fixes, rebuilds, re-reviews; it stops when
    nothing applies, the director is skipped, or the score does not improve (the better build is kept)."""
    cur, rep = directed, with_director(report, review(report))
    rounds = []
    for n in range(1, max(0, min(max_rounds, 2)) + 1):
        d = rep.get("director") or {}
        if d.get("status") != "ok" and not gate_fixes(rep):
            rounds.append({"round": n, "stopped": d.get("note", "no director and no gate fixes")})
            break
        fixes = gate_fixes(rep) + [i for i in d.get("issues", []) if i["severity"] in ("high", "medium")]
        new, applied, rejected, human = apply_fixes(cur, fixes)
        if not applied:
            rounds.append({"round": n, "stopped": "nothing applicable", "rejected": rejected, "needs_human": human})
            break
        rep2 = with_director(rebuild(new), None)
        rep2 = with_director(rep2, review(rep2))
        rounds.append({"round": n, "applied": applied, "rejected": rejected, "needs_human": human,
                       "score_before": rep["score"], "score_after": rep2["score"]})
        if rep2["score"] <= rep["score"]:
            rounds[-1]["stopped"] = "score did not improve: kept the previous build"
            break
        cur, rep = new, rep2
    return {"directed": cur, "report": rep, "rounds": rounds}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reel_director.review", description=__doc__.splitlines()[0])
    ap.add_argument("build")
    ap.add_argument("--out", help="output dir (default: the build dir)")
    ap.add_argument("--director", action="store_true", help="run the headless claude -p director review")
    ap.add_argument("--director-json", help="validate + use a saved director answer instead of calling the CLI")
    ap.add_argument("--timeout", type=float, default=TIMEOUT)
    ap.add_argument("--model")
    ap.add_argument("--apply", action="store_true", help="write directed.fixed.json (whitelisted ops only)")
    a = ap.parse_args(argv)
    build, out = Path(a.build), Path(a.out or a.build)
    rep = run_qa(build, out)
    shots = [s["id"] for s in json.loads((build / "reel" / "timeline.json").read_text())["shots"]]
    d = None
    if a.director_json:
        d = {**validate(json.loads(Path(a.director_json).read_text())), "source": str(a.director_json)}
    elif a.director:
        d = run_director(out, rep, shots, timeout=a.timeout, model=a.model)
    rep = with_director(rep, d)
    (out / "qa" / "report.json").write_text(json.dumps(rep, indent=1))
    if d is not None:
        (out / "qa" / "director.json").write_text(json.dumps(d, indent=1))
        print(json.dumps(d, indent=1))
    if a.apply and (build / "directed.json").exists():
        fixes = gate_fixes(rep) + [i for i in (d or {}).get("issues", []) if i["severity"] in ("high", "medium")]
        new, applied, rejected, human = apply_fixes(json.loads((build / "directed.json").read_text()), fixes)
        (out / "directed.fixed.json").write_text(json.dumps(new, indent=1))
        (out / "qa" / "fixes.json").write_text(json.dumps({"applied": applied, "rejected": rejected,
                                                           "needs_human": human}, indent=1))
        print(f"fixes: {len(applied)} applied, {len(rejected)} rejected, {len(human)} for a human")
    print(f"score {rep['score']} (gates {rep['gate_score']})  verdict {rep['verdict']}")
    return 0 if rep["verdict"] == "ship" else 1


if __name__ == "__main__":
    raise SystemExit(main())
