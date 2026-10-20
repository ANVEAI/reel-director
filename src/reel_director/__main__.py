"""CLI.

  python -m reel_director validate script.json
  python -m reel_director prep takes.json --out work/prepped [--no-denoise] [--matte]
  python -m reel_director direct script.json --out directed.json [--takes work/prepped/takes.json] [--preset NAME]
  python -m reel_director compile script.json --out work/reel [--takes work/prepped/takes.json]
                                  [--preset NAME] [--no-auto] [--no-mix]
  python -m reel_director deliver renders/reel.mp4 work/mix/mix.wav renders/reel-master.mp4
  python -m reel_director review <build> [--director | --director-json F] [--rounds 0-2 --takes prepped/takes.json]
  python -m reel_director learn creator <project> | learn reference <videos...> --out style-ref.json
  python -m reel_director media status | search "<query>" | pick <build> | fetch|swap|reject <build> <slot>
                                | credits <build>        (B-roll: media_cli.py)
  python -m reel_director master renders/reel.mp4 renders/reel-master.mp4   (mode B fallback)
  python -m reel_director transcribe take.mp4 --out take.words.json
  python -m reel_director check-take take.mp4 --script script.json --shot hook --out take.qa.json
  python -m reel_director studio script.json --project work/myreel [--port 8765] [--no-open]

takes.json maps shot ids to one or more recordings (paths relative to takes.json); "words"
is optional for prep, which transcribes. "pin": true makes the auto-picker use that take:
  {"hook": [{"src": "hook-1.mp4"}, {"src": "hook-2.mp4", "words": "hook-2.words.json", "pin": true}]}

prep also writes a face track next to each cleaned take (<take>.face.json, Apple Vision) and, with --matte,
<take>.bg.mp4: the take with its background blurred + dimmed under the person matte (used by the looks).
compile runs the director (auto cues -> <out>/../directed.json, never script.json), resolves its media B-roll
(picks + downloads -> media.json, credits -> <out>/../renders/reel.credits.txt; RD_MEDIA_OFFLINE=1 = no network),
bakes the sound into <out>/../mix/mix.wav and writes the HyperFrames project (face-aware layout -> reel/layout.json);
render it, then `deliver`, then `review`: QA gates on the rendered master -> <build>/qa/report.json and the
before/after sheet -> <build>/renders/before-after.png; --director adds the headless editing director and
--rounds applies its whitelisted fixes and rebuilds (<= 2 rounds, kept only when the score improves).
Presets: bold-hustle, clean-pro (default), beast-hype, editorial, tech-explainer, desi-bilingual (beta).
"""
import argparse
import json
import sys
from pathlib import Path

from .media import media_duration
from .schema import ScriptError, load_script

WHISPER = "mlx-community/whisper-large-v3-turbo"


def _entries(path: Path) -> dict[str, list[dict]]:
    raw = json.loads(path.read_text())
    return {sid: v if isinstance(v, list) else [v] for sid, v in raw.items()}


def load_takes(path: Path) -> dict:
    from .timeline import Take
    from .timing import load_asr_words
    base, takes = path.parent, {}
    for sid, entries in _entries(path).items():
        takes[sid] = []
        for t in entries:
            if "words" not in t:
                raise ScriptError(f"take {t['src']!r} of shot {sid!r} has no words; run prep first")
            src = (base / t["src"]).resolve()
            takes[sid].append(Take(src, load_asr_words(base / t["words"]), media_duration(src), bool(t.get("pin"))))
    return takes


def transcribe(media: Path, model: str = WHISPER) -> list[dict]:
    import mlx_whisper   # must load before torch (see scripts/smoke_test.py)
    r = mlx_whisper.transcribe(str(media), path_or_hf_repo=model, word_timestamps=True)
    return [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)}
            for seg in r["segments"] for w in seg["words"]]


def cmd_validate(args) -> int:
    from .timing import estimate
    s = load_script(args.script)
    total = 0.0
    for shot in s.shots:
        est = estimate(shot)[-1].end
        total += est
        print(f"  {shot.id:<12} {len(shot.words):>3} words  ~{est:4.1f}s  {len(shot.cues)} cue(s)")
    print(f"ok: {len(s.shots)} shots, ~{total:.1f}s estimated read")
    return 0


def cmd_prep(args) -> int:
    from .audio import clean_take
    src_json, out = Path(args.takes), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []   # (sid, cleaned path, words path, pinned)
    for sid, entries in _entries(src_json).items():
        for k, t in enumerate(entries, 1):
            clean = out / f"{sid}-{k}.mp4"
            lv = clean_take((src_json.parent / t["src"]).resolve(), clean, denoise=not args.no_denoise)
            print(f"  {clean.stem}: {lv['before_lufs']:.1f} -> {lv['after_lufs']:.1f} LUFS")
            jobs.append((sid, clean, out / f"{sid}-{k}.words.json", bool(t.get("pin"))))
    raw = {clean: transcribe(clean) for _, clean, _, _ in jobs}   # all mlx work before torch loads

    from .audio import speech_spans
    from .cleanup import snap_to_speech
    prepped: dict[str, list] = {}
    for sid, clean, words_path, pin in jobs:
        words = snap_to_speech(raw[clean], speech_spans(clean))
        words_path.write_text(json.dumps(words, indent=1))
        prepped.setdefault(sid, []).append({"src": clean.name, "words": words_path.name, "pin": pin})
        print(f"  {clean.stem}: {len(words)} words")
    (out / "takes.json").write_text(json.dumps(prepped, indent=2))
    prep_looks([clean for _, clean, _, _ in jobs], out, args.matte)
    print(f"wrote {out / 'takes.json'}")
    return 0


def prep_looks(cleaned: list[Path], out: Path, matte: bool) -> None:
    """Face track per cleaned take (prepped/<take>.face.json: layout, reframe, punch origin) and, with --matte,
    the background-treated picture (prepped/<take>.bg.mp4). Without Apple Vision both are skipped with a note."""
    from .face import FaceUnavailable, prep_faces
    cleaned = [c for c in cleaned if c.exists()]
    try:
        prep_faces(cleaned, out)
    except Exception as e:      # the face track is an enhancement: layout falls back to the v1 band without it
        print(f"  face track failed ({type(e).__name__}: {e}): captions use the v1 band")
    if not matte:
        return
    from .matte import treat_background
    for clean in cleaned:
        try:
            r = treat_background(clean, clean.with_name(clean.stem + ".bg.mp4"))
        except FaceUnavailable as e:
            print(f"  background treatment skipped: {e}")
            return
        print(f"  {clean.stem}: background blurred {r['blur']:g} px, dimmed {r['dim']:.0%} -> {clean.stem}.bg.mp4")


def _takes_arg(args) -> dict:
    return load_takes(Path(args.takes)) if getattr(args, "takes", None) else {}


def cmd_direct(args) -> int:
    from . import pipeline
    from .timeline import build_timeline
    s = pipeline.load(args.script, args.preset)
    takes = _takes_arg(args)
    notes: list[str] = []
    d = pipeline.direct(s, takes, args.no_auto, notes)
    path = pipeline.write_directed(d, args.out)
    m = pipeline.policy.metrics(d, build_timeline(d, takes))
    n = sum(1 for sh in d.shots for c in sh.cues if c.params.get("auto"))
    print(f"  preset {d.style.get('preset')}, pace {d.style.get('pace')}: {n} auto cue(s), {m['visual_changes']} "
          f"visual changes, median gap {m['median_gap_s']}s, CV {m['cv']}, B-roll {m['broll_on_screen']:.0%} "
          f"(face-off {m['broll_share']:.0%})")
    for line in notes:
        print(f"  note: {line}")
    print(f"wrote {path}")
    return 0


def cmd_compile(args) -> int:
    from . import pipeline
    r = pipeline.build(args.script, args.out, _takes_arg(args), args.preset, args.no_auto, not args.no_mix)
    tl = r["timeline"]
    if r["beta"]:
        print(f"  preset {r['preset']} is beta: Devanagari lines are not read yet (Roman Hinglish works)")
    for p in tl.shots:
        if not p.take:
            print(f"  {p.shot.id:<10} {p.out_start:6.2f}s +{p.duration:5.2f}s  slot (not recorded)")
            continue
        warn = "  <-- re-record?" if p.coverage < 0.85 else ""
        warn += "  (pinned)" if p.take.pin else ""
        print(f"  {p.shot.id:<10} {p.out_start:6.2f}s +{p.duration:5.2f}s  take {p.take_index + 1}/{len(p.scores)}, "
              f"{len(p.clips) - 1} cut(s){warn}")
        for k, sc in enumerate(p.scores):
            mark = "*" if k == p.take_index else " "
            print(f"      {mark} take {k + 1}: {sc.describe()}")
    m = r["metrics"]
    print(f"  director: preset {r['preset']}, {m['visual_changes']} visual changes, median gap {m['median_gap_s']}s, "
          f"max static {m['max_static_s']}s, B-roll {m['broll_on_screen']:.0%} (face-off {m['broll_share']:.0%}), "
          f"{m['transitions']} transition(s), "
          f"{m['sfx']} sfx -> {r['directed_path']}")
    for line in r["notes"]:
        print(f"  note: {line}")
    if r.get("credits"):
        print(f"  credits: {len(r['credits'])} line(s) -> {Path(args.out).parent / 'renders' / 'reel.credits.txt'}")
    if r["mix_report"]:
        mm = r["mix_report"]["master"]
        print(f"  mix: {mm['lufs']:.1f} LUFS, true peak {mm['true_peak_4x']:.1f} dBTP -> {r['mix']}")
    print(f"wrote {r['index']} ({tl.duration:.2f}s)")
    return 0


def cmd_deliver(args) -> int:
    from .audio import deliver
    r = deliver(Path(args.render), Path(args.mix), Path(args.dst))
    print(f"deliver: {r['lufs']:.1f} LUFS, true peak {r['true_peak']:.1f} dBTP, {r['passes']} pass(es), "
          f"A/V offset {r['av_start_offset_ms']:.1f} ms: {args.dst}")
    print("@deliver " + json.dumps(r))
    if not r.get("ok"):
        print("error: the delivered file misses -14 +-0.5 LUFS / -1.5 dBTP after 3 trim rounds", file=sys.stderr)
        return 3
    return 0


def cmd_review(args) -> int:
    from . import pipeline
    build = Path(args.build)
    tj = Path(args.takes) if args.takes else build / "prepped" / "takes.json"
    takes = load_takes(tj) if args.rounds and tj.exists() else None
    r = pipeline.review_build(build, takes, args.director, args.director_json, args.rounds, timeout=args.timeout)
    for g in r["gates"]:
        print(f"  [{g['level']:>4}] {g['id']:<17} {g['message']}")
    d = r.get("director")
    if d:
        print(f"  director: {d.get('status')}" + (f", score {d['score']}, {len(d['issues'])} issue(s)"
                                                  if d.get("status") == "ok" else f": {d.get('note')}"))
    for h in r.get("rounds", []):
        print(f"  round {h['round']}: " + (h.get("stopped") or f"{h['score_before']} -> {h['score_after']}"))
    print(f"score {r['score']} (gates {r['gate_score']}), verdict {r['verdict']}, final {r['final']}: "
          f"{build / 'qa' / 'report.json'}, {build / r['before_after']}")
    print("@review " + json.dumps({k: r.get(k) for k in ("score", "gate_score", "verdict", "final")}))
    return 0


def cmd_master(args) -> int:
    from .audio import master
    r = master(Path(args.src), Path(args.dst))
    print(f"{r['before_lufs']:.1f} -> {r['after_lufs']:.1f} LUFS, true peak {r['true_peak']:.1f} dBTP: {args.dst}")
    return 0


def cmd_transcribe(args) -> int:
    words = transcribe(Path(args.media), args.model)
    Path(args.out).write_text(json.dumps(words, indent=1))
    print(f"wrote {args.out} ({len(words)} words)")
    return 0


def cmd_check_take(args) -> int:
    from .takecheck import check_take
    capture = json.loads(Path(args.capture_info).read_text()) if args.capture_info else None
    r = check_take(Path(args.media), Path(args.script), args.shot, Path(args.out),
                   Path(args.source) if args.source else None, capture, lambda m: transcribe(m, args.model))
    for c in r["checks"]:
        print(f"  [{c['level']:>4}] {c['message']}")
    print(f"{r['take']}: {r['verdict']} (script score {r['script']['score']}) -> {args.out}")
    return 0


def cmd_studio(args) -> int:
    from .studio.server import serve
    return serve(Path(args.script), Path(args.project), args.port, open_browser=not args.no_open)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["learn"]:              # its own sub-commands and --help (learn.py)
        from .learn import main as learn_main
        return learn_main(argv[1:])
    if argv[:1] == ["media"]:              # B-roll sources, picks, decisions, credits (media_cli.py)
        from .media_cli import main as media_main
        return media_main(argv[1:])
    ap = argparse.ArgumentParser(prog="reel_director")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("script")
    p = sub.add_parser("prep")
    p.add_argument("takes")
    p.add_argument("--out", required=True)
    p.add_argument("--no-denoise", action="store_true")
    p.add_argument("--matte", action="store_true", help="also bake <take>.bg.mp4 (background blur + dim, ~2x realtime)")
    c = sub.add_parser("compile")
    c.add_argument("script")
    c.add_argument("--out", required=True)
    c.add_argument("--takes")
    c.add_argument("--preset", help="style preset (default: the script's, else clean-pro)")
    c.add_argument("--no-auto", action="store_true", help="no director: manual cues only")
    c.add_argument("--no-mix", action="store_true", help="legacy sound: per-clip voice in the page, then master")
    dr = sub.add_parser("direct", help="add the director's auto cues; writes directed.json")
    dr.add_argument("script")
    dr.add_argument("--out", required=True)
    dr.add_argument("--takes", help="prepped takes.json: real word times instead of the read estimate")
    dr.add_argument("--preset")
    dr.add_argument("--no-auto", action="store_true")
    dl = sub.add_parser("deliver", help="mux the render with the baked mix; verify -14 LUFS / -1.5 dBTP")
    dl.add_argument("render")
    dl.add_argument("mix")
    dl.add_argument("dst")
    rv = sub.add_parser("review", help="QA gates + before/after on a rendered build (+ the editing director)")
    rv.add_argument("build", help="dir with reel/, directed.json, renders/reel-master.mp4")
    rv.add_argument("--director", action="store_true", help="headless `claude -p` editing director review")
    rv.add_argument("--director-json", help="a saved director answer instead of calling the CLI")
    rv.add_argument("--rounds", type=int, default=0, choices=[0, 1, 2], help="fix rounds (rebuild + re-review)")
    rv.add_argument("--takes", help="prepped takes.json for the rebuilds (default: <build>/prepped/takes.json)")
    rv.add_argument("--timeout", type=float, default=None, help="director timeout, s")
    ln = sub.add_parser("learn", add_help=False, help="creator profile (coach) or a style reference from your own videos")
    ln.add_argument("rest", nargs=argparse.REMAINDER)
    md = sub.add_parser("media", add_help=False, help="B-roll: sources, search, picks (media.json), credits")
    md.add_argument("rest", nargs=argparse.REMAINDER)
    m = sub.add_parser("master")
    m.add_argument("src")
    m.add_argument("dst")
    t = sub.add_parser("transcribe")
    t.add_argument("media")
    t.add_argument("--out", required=True)
    t.add_argument("--model", default=WHISPER)
    k = sub.add_parser("check-take", help="QA one take: technical checks + did it read the script")
    k.add_argument("media")
    k.add_argument("--script", required=True)
    k.add_argument("--shot", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--source", help="the original upload, for frame-rate and clipping forensics")
    k.add_argument("--capture-info", help="capture metadata JSON saved by the studio")
    k.add_argument("--model", default=WHISPER)
    st = sub.add_parser("studio", help="record, check and build in the browser")
    st.add_argument("script")
    st.add_argument("--project", required=True)
    st.add_argument("--port", type=int, default=8765)
    st.add_argument("--no-open", action="store_true")
    args = ap.parse_args(argv)
    cmds = {"validate": cmd_validate, "prep": cmd_prep, "compile": cmd_compile, "master": cmd_master,
            "direct": cmd_direct, "deliver": cmd_deliver, "review": cmd_review,
            "transcribe": cmd_transcribe, "check-take": cmd_check_take, "studio": cmd_studio}
    from .studio.project import ProjectError
    try:
        return cmds[args.cmd](args)
    except (ScriptError, ProjectError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
