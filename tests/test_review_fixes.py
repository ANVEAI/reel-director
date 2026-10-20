"""Regression tests for the v1 review findings fixed by TEAM FIXES (edit + studio dimensions)."""
import re
import subprocess
import threading
from pathlib import Path

import pytest

from reel_director import takecheck as tc
from reel_director.cleanup import keep_segments, snap_to_speech
from reel_director.schema import parse_script
from reel_director.studio.project import best_take, build_candidates
from reel_director.takecheck import assess, script_check, script_diff, verdict
from reel_director.textnorm import _CANON, norm_tokens, spoken_value
from reel_director.timeline import Take, build_timeline, pick_take
from reel_director.timing import align, load_asr_words

STATIC = Path(__file__).resolve().parents[1] / "src" / "reel_director" / "studio" / "static"


def shot(line):
    return parse_script({"shots": [{"id": "a", "line": line}]}).shots[0]


def said(text, t0=0.4, d=0.3, gaps=None):
    """ASR words of `text`, `d` s each; gaps={index: extra silence before that word}."""
    out, t = [], t0
    for i, w in enumerate(text.split()):
        t += (gaps or {}).get(i, 0.0)
        out.append({"w": w, "s": round(t, 3), "e": round(t + d, 3)})
        t += d
    return out


def reel_words(asr, segs):
    return [w["w"] for w in asr if any(s.media_in <= (w["s"] + w["e"]) / 2 <= s.media_out for s in segs)]


def qa(line, heard_words, dur=None):
    s = shot(line)
    dur = dur or heard_words[-1]["e"] + 0.6
    r = script_check(s, heard_words, dur)
    checks = assess({"duration": dur, "luma_mean": 120, "effective_9x16": [1080, 1920], "blur": 5.0, "fps": 30},
                    {"peak_dbfs": -6, "clipped_samples": 0, "lufs": -20, "snr_db": 40}, r, len(s.words), 0)
    return r, verdict(checks)


# --- finding 0: spelling variants with a different token count ---------------------------------

@pytest.mark.parametrize("line,heard", [
    ("Most creators waste three hours editing one reel with A.I. tools every week.",
     "Most creators waste three hours editing one reel with AI tools every week."),
    ("Plan, shoot & edit your next reel in under ten minutes flat.",
     "Plan, shoot and edit your next reel in under ten minutes flat."),
    ("This was my 1st reel and it got ten thousand views overnight.",
     "This was my first reel and it got ten thousand views overnight."),
    ("Post every day at 5pm and watch your reach grow fast.",
     "Post every day at 5 p.m. and watch your reach grow fast."),
    ("That one reel got me 1,000,000 views in a single week.",
     "That one reel got me 1 million views in a single week."),
    ("Honestly it's the fastest way to edit your reels today.",
     "Honestly it is the fastest way to edit your reels today."),
    ("Alright, let's go and make this reel together now.",
     "All right, let's go and make this reel together now."),
    ("Send me an e-mail and I will set up the call.",
     "Send me an email and I will setup the call."),
    ("I'm gonna show you how this works in a minute.",
     "I am going to show you how this works in a minute."),
    ("It's 10x faster than editing by hand every day.",
     "It's ten times faster than editing by hand every day."),
])
def test_variant_reads_keep_every_word_and_pass(line, heard):
    asr = said(heard)
    al = align(shot(line), asr)
    segs = keep_segments(al, asr, asr[-1]["e"] + 0.6)
    assert reel_words(asr, segs) == heard.split()         # nothing the creator said is cut
    r, v = qa(line, asr)
    assert r["coverage"] == 1.0 and not r["misread"] and not r["junk"] and v == "great"


def test_unequal_block_with_a_different_word_is_a_misread_not_a_cut():
    line = "Most creators waste three hours editing one reel."
    asr = said("Most creators uh lose three hours editing one reel.")
    r, v = qa(line, asr)
    assert r["misread"] == [{"expected": "waste", "heard": "lose"}] and v == "retake"
    al = align(shot(line), asr)
    segs = keep_segments(al, asr, asr[-1]["e"] + 0.6)
    assert "lose" in reel_words(asr, segs) and "uh" not in reel_words(asr, segs)   # filler still cut


def test_whisper_number_split_across_words_is_one_number():
    asr = said("We hit 10 ,000 followers today.")
    r, v = qa("We hit 10,000 followers today.", asr)
    assert r["coverage"] == 1.0 and not r["junk"] and v == "great"


def test_norm_forms():
    assert norm_tokens("A.I.") == ["ai"] and norm_tokens("5pm") == norm_tokens("5 p.m.") == ["five", "pm"]
    assert norm_tokens("1,000,000") == norm_tokens("1 million") == ["one", "million"]
    assert norm_tokens("21st") == ["twenty", "first"] and norm_tokens("12th") == ["twelfth"]
    assert norm_tokens("$2.5M") == norm_tokens("$2.5 million") and norm_tokens("10k") == ["ten", "thousand"]
    assert norm_tokens("&") == ["and"] and norm_tokens("1.5x") == ["one", "point", "five", "x"]
    assert norm_tokens("x.com") == ["x", "com"]
    assert spoken_value("twenty five hundred dollars".split()) == (2500, ("dollars",))
    assert spoken_value(norm_tokens("$2,500")) == (2500, ("dollars",))


# --- finding 1: numbers read with tokens dropped ----------------------------------------------

@pytest.mark.parametrize("line,heard,expected,got", [
    ("We hit 3,000 followers in a week.", "We hit three followers in a week.", "3,000", "three"),
    ("It costs $2,500 a month.", "It costs two thousand a month.", "$2,500", "two thousand"),
    ("Engagement went up 40% overnight.", "Engagement went up forty overnight.", "40%", "forty"),
])
def test_partly_read_number_is_a_misread(line, heard, expected, got):
    r, v = qa(line, said(heard))
    assert r["misread"] == [{"expected": expected, "heard": got}] and r["coverage"] < 1 and v == "retake"


@pytest.mark.parametrize("heard", ["We hit 3,000 followers in a week.", "We hit three thousand followers in a week.",
                                   "We hit three uh thousand followers in a week."])
def test_full_number_reads_stay_great(heard):
    r, v = qa("We hit 3,000 followers in a week.", said(heard))
    assert r["coverage"] == 1.0 and not r["misread"] and v == "great"


def test_same_number_said_another_way_is_not_a_misread():
    r, v = qa("It costs $2,500 a month.", said("It costs twenty five hundred dollars a month."))
    assert r["coverage"] == 1.0 and not r["misread"] and v == "great"


def test_picker_prefers_the_complete_number_read():
    s = shot("We hit 3,000 followers in a week.")
    good = Take(Path("a.mp4"), said("We hit three thousand followers in a week."), 3.5)
    bad = Take(Path("b.mp4"), said("We hit three followers in a week."), 3.2)
    (idx, *_), _ = pick_take(s, [good, bad])
    assert idx == 0


# --- finding 2: Whisper hallucination over trailing silence -----------------------------------

def test_hallucinated_tail_never_beats_the_real_read():
    line = "Follow for part two. Thanks for watching!"
    asr = (said("Follow for part two.", t0=0.5) + [{"w": "Um,", "s": 2.0, "e": 2.4}]
           + said("Thanks for watching!", t0=2.5) + said("Thanks for watching!", t0=5.0))
    speech = [(0.45, 1.75), (1.95, 3.45)]
    words = snap_to_speech(asr, speech)
    assert [w.get("speech", True) for w in words[-3:]] == [False] * 3
    al = align(shot(line), words)
    assert al.times[-1].end <= 3.45 and al.ignored == frozenset(range(len(words) - 3, len(words)))
    segs = keep_segments(al, words, 6.5)
    assert segs[-1].media_out <= 3.45 + 0.35 + 1e-6            # no trailing silence kept
    r = script_check(shot(line), words, 6.5)
    assert r["coverage"] == 1.0 and r["junk"] == ["Um,"]        # the hallucination isn't "extra words"


def test_unvoiced_real_word_is_still_used_when_nothing_else_places_it():
    words = snap_to_speech(said("Most creators waste three hours."), [(0.35, 1.25)])
    assert words[-1].get("speech") is False
    al = align(shot("Most creators waste three hours."), words)
    assert al.coverage == 1.0 and len(al.used_asr) == 5


def test_no_speech_spans_flag_nothing_and_flags_survive_words_json(tmp_path):
    assert all("speech" not in w for w in snap_to_speech(said("a b c"), []))
    f = tmp_path / "w.json"
    f.write_text('[{"w": "hi", "s": 0, "e": 1, "speech": false}, {"w": "yo", "s": 1, "e": 2}]')
    assert [w.get("speech") for w in load_asr_words(f)] == [False, None]


# --- finding 7: spelling variants with the same token count -----------------------------------

@pytest.mark.parametrize("line,heard", [("OK, here's the plan for today.", "Okay, here's the plan for today."),
                                        ("Okay, here's the plan for today.", "OK, here's the plan for today."),
                                        ("Pick a colour that works for you.", "Pick a color that works for you.")])
def test_spelling_variant_is_not_a_misread(line, heard):
    r, v = qa(line, said(heard))
    assert not r["misread"] and r["coverage"] == 1.0 and v == "great"


def test_real_one_letter_misread_still_fails():
    misread, _ = script_diff(shot("You can't do this alone."), said("You can do this alone."))
    assert misread == [{"expected": "can't", "heard": "can"}]


# --- reel 2 (2026-10-21): Whisper drops a possessive 's ---------------------------------------

@pytest.mark.parametrize("line,heard", [("SpaceX's first three launches all failed.", "SpaceX first three launches all failed."),
                                        ("My client's reel went viral overnight.", "My client reel went viral overnight."),
                                        ("My client's reel went viral overnight.", "My clients reel went viral overnight.")])
def test_dropped_possessive_is_not_a_misread(line, heard):
    r, v = qa(line, said(heard))
    assert not r["misread"] and r["coverage"] == 1.0 and v == "great"


@pytest.mark.parametrize("line,heard,expected,got", [
    ("He's ready to post today.", "He ready to post today.", "He's", "He"),              # an "is" contraction
    ("SpaceX's first three launches all failed.", "SpaceX's first three launched all failed.", "launches", "launched"),
])
def test_contraction_or_inflection_is_still_a_misread(line, heard, expected, got):
    misread, _ = script_diff(shot(line), said(heard))
    assert misread == [{"expected": expected, "heard": got}]


def test_every_canonical_word_is_in_one_group():
    from reel_director.textnorm import _HOMOPHONES, _SPELLINGS
    words = [w for g in (_HOMOPHONES + "|" + _SPELLINGS).split("|") for w in g.split()]
    assert len(words) == len(set(words)) == len(_CANON)


# --- finding 9: skipped word dead air ---------------------------------------------------------

def test_skipped_word_does_not_keep_the_pause():
    line = "Most creators waste three hours editing one reel every single week."
    asr = said("Most creators waste three hours one reel every single week.", t0=0.5, d=0.38, gaps={5: 1.6})
    s = shot(line)
    al = align(s, asr)
    segs = keep_segments(al, asr, asr[-1]["e"] + 0.6)
    hours_end, one_start = asr[4]["e"], asr[5]["s"]
    kept = sum(max(0.0, min(g.media_out, one_start) - max(g.media_in, hours_end)) for g in segs)
    assert kept <= 0.2 + 1e-6
    tl = build_timeline(parse_script({"shots": [{"id": "a", "line": line}]}),
                        {"a": [Take(Path("t.mp4"), asr, asr[-1]["e"] + 0.6)]})
    w = tl.shots[0].words[5]
    assert w.end - w.start < 0.15
    r, v = qa(line, asr)
    assert v == "ok" and any(c for c in [r["missing"]] if c == ["editing"])   # QA names the skip


def test_short_gap_with_a_skipped_word_is_not_cut():
    asr = said("Most creators waste three hours one reel.", gaps={5: 0.3})
    segs = keep_segments(align(shot("Most creators waste three hours editing one reel."), asr), asr, 4.0)
    assert len(segs) == 1


# --- finding 22: a silent take leads with the mic ---------------------------------------------

def test_silent_take_leads_with_the_mic_not_the_script():
    script = {"coverage": 0.0, "missing": "Most creators waste".split(), "misread": [], "junk": [], "cuts": 0}
    checks = assess({"duration": 3, "luma_mean": 120, "effective_9x16": [1080, 1920], "blur": 5.0, "fps": 30},
                    {"peak_dbfs": -60, "clipped_samples": 0, "lufs": -61.0, "snr_db": 1.3}, script, 3, 2.9)
    fails = [c["id"] for c in checks if c["level"] == "fail"]
    assert fails[0] == "silent" and "coverage" in fails and verdict(checks) == "retake"
    assert "microphone" in checks[0]["message"]


# --- finding 61 / 17: QA-crashed takes and retake-only shots -----------------------------------

def rep(score, v="great"):
    return {"verdict": v, "script": {"score": score}}


def test_take_without_a_qa_report_never_displaces_reviewed_takes():
    entries = [{"name": "t-1"}, {"name": "t-9"}, {"name": "t-12"}]
    reports = {"t-1": rep(80, "retake"), "t-9": None, "t-12": rep(70, "retake")}
    assert [e["name"] for e in build_candidates(entries, reports)] == ["t-1", "t-12"]
    assert best_take(entries, {k: v for k, v in reports.items() if v}) == "t-1"
    assert build_candidates([{"name": "t-9"}], {"t-9": None}) == []


def test_star_matches_the_build_candidates():
    entries = [{"name": "h-1"}, {"name": "h-2"}]
    reports = {"h-1": rep(99, "retake"), "h-2": rep(70, "ok")}
    assert best_take(entries, reports) == "h-2" == build_candidates(entries, reports)[0]["name"]


def test_studio_ui_blocks_build_on_retake_only_shots_and_keeps_restarted_takes():
    build, shots, studio, rec = ((STATIC / f).read_text() for f in ("build.js", "shots.js", "studio.js", "recorder.js"))
    assert "export const usableTake = t => t.status === 'ready' && (t.pin || takeVerdict(t) !== 'retake')" in shots
    assert "shotReadiness(s) === 'retake'" in build and "Pin a take to build with it anyway" in build
    restart = studio[studio.index("function restartTake"):studio.index("// --- keyboard")]
    assert "setAside: true" in restart and "S.rec === 'idle') return" in restart
    # the recorder is detached before cancelCountdown() (which aborts S.recorder) runs
    assert restart.index("S.recorder = null") < restart.index("cancelCountdown()") < restart.index("r.stop()")
    mimes = re.findall(r"'(video/[^']+)'", rec[rec.index("MIMES"):rec.index("];")])
    assert mimes[0].startswith("video/mp4;codecs=avc3") and mimes.index("video/mp4;codecs=avc1,mp4a.40.2") > 1


# --- unverified findings, reproduced then fixed -------------------------------------------------

def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    enc = ["-c:v", "libx264", "-crf", "14", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    base = "testsrc2=s=1080x1920:r=30:d=1"
    _ff("-f", "lavfi", "-i", f"{base}[s];{base},gblur=sigma=8[bg];[s]crop=600:900:240:400[c];[bg][c]overlay=240:400",
        *enc, str(d / "sharp_on_blur.mp4"))
    _ff("-f", "lavfi", "-i", "color=c=0xF0F0EC:s=1080x1920:r=30:d=1", "-f", "lavfi", "-i", "color=c=0xC8A08C:s=600x900:r=30:d=1",
        "-filter_complex", "[1:v]drawgrid=w=40:h=40:t=2:c=0x806050[f];[0:v][f]overlay=240:260", *enc, str(d / "face_on_white.mp4"))
    _ff("-f", "lavfi", "-i", base, "-vf", "gblur=sigma=3", *enc, str(d / "soft.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3:sample_rate=48000",
        *enc, "-c:a", "aac", "-shortest", str(d / "clean.mp4"))
    b = bytearray((d / "clean.mp4").read_bytes())
    for k in range(6):                # what two converters writing one file leave: garbage inside the media data
        a = len(b) * (3 + k) // 10
        b[a:a + 4096] = bytes((i * 37 + k) % 251 for i in range(4096))
    (d / "corrupt.mp4").write_bytes(bytes(b))
    return d


def _video_problems(path, audio=False):
    v = {**tc.video_stats(path, 1080, 1920), "fps": 30}
    errs: list[str] = []
    if audio:
        tc.decode_audio(path, errors=errs)
    v["decode_errors"] += len(errs)
    return [c["id"] for c in tc._video_checks(v, 1080) if c["level"] != "ok"]


def test_sharp_subject_on_a_defocused_background_is_not_soft(clips):     # finding 34
    assert _video_problems(clips / "sharp_on_blur.mp4") == []
    assert _video_problems(clips / "soft.mp4") == ["focus"]


def test_white_wall_behind_a_lit_face_is_not_too_bright(clips):          # finding 35
    v = tc.video_stats(clips / "face_on_white.mp4", 1080, 1920)
    assert v["luma_mean"] > tc.LUMA_BRIGHT > v["subject_luma"] > tc.LUMA_DARK
    assert _video_problems(clips / "face_on_white.mp4") == []


def test_damaged_take_fails_qa(clips):                                    # finding 60 (QA side)
    assert _video_problems(clips / "clean.mp4", audio=True) == []
    assert "corrupt" in _video_problems(clips / "corrupt.mp4", audio=True)


def test_film_rate_import_is_not_low_light():                             # finding 37
    v = {"luma_mean": 120, "effective_9x16": [1080, 1920], "blur": 5.0, "fps": 23.98}
    assert not [c for c in tc._video_checks(v, 1080) if c["id"] == "fps"]
    assert [c for c in tc._video_checks({**v, "fps": 15.0}, 1080) if c["id"] == "fps"]


def test_two_studios_on_one_folder_lose_no_take(tmp_path):                # finding 67
    from reel_director.studio.project import Project
    script = tmp_path / "script.json"
    script.write_text('{"shots": [{"id": "hook", "line": "Hello there."}]}')
    a, b = Project(tmp_path / "p", script), Project(tmp_path / "p", script)
    names, errors = [], []

    def run(p):
        for _ in range(25):
            try:
                n, _ = p.reserve("hook", "mp4")
                p.add("hook", n)
                names.append(n)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
    ts = [threading.Thread(target=run, args=(p,)) for p in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(set(names)) == 50 and len(a.takes()["hook"]) == 50
