"""Take cleanup: which parts of a take to keep, and which take of a shot is best."""
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .timing import Alignment

PRE_ROLL = 0.15     # keep this much before the first word of a take
POST_ROLL = 0.35    # and after the last word
PAD_BEFORE = 0.08   # around a cut, so word onsets/tails survive timestamp error
PAD_AFTER = 0.12
MAX_PAUSE = 0.45    # silences between script words longer than this get shortened
MIN_CUT = 0.06      # cuts that would remove less than this aren't worth a jump
# shot-to-shot seams (HQ review, real-1: PRE_ROLL + POST_ROLL left 0.50 s of dead air at every shot change).
# Measured on the founder's takes: speech starts within 20 ms of the ASR start, but a word's tail rings on up
# to 0.30 s past its ASR end ('record?'). So a seam keeps SEAM_HEAD before the voiced onset and SEAM_TAIL
# after the voiced offset (energy within SEAM_DB of the take's loud speech), never inside a word.
SEAM_HEAD, SEAM_TAIL, SEAM_DB, SEAM_WIN, SEAM_GAP = 0.04, 0.06, 30.0, 0.02, 0.08


@dataclass
class Segment:
    media_in: float
    media_out: float

    @property
    def duration(self) -> float:
        return self.media_out - self.media_in


def junk_between(al: Alignment, asr: list[dict], a_end: float, b_start: float) -> list[dict]:
    """ASR words in a gap that aren't part of the script read: fillers, false starts, ad-libs."""
    return [w for j, w in enumerate(asr)
            if j not in al.used_asr and a_end - 0.02 <= (w["s"] + w["e"]) / 2 <= b_start + 0.02]


def keep_segments(al: Alignment, asr: list[dict], take_duration: float) -> list[Segment]:
    """Cut every gap between consecutive script words that holds junk or a long pause.

    Padding around kept words never reaches into a junk word, so a restart said with no
    pause ("...edit was, what if...") doesn't leak its tail into the keeper read.

    Pauses are measured between words the take actually backs: a skipped word's interpolated
    span would otherwise fill the silence and hide it from the cutter (timeline snaps such a
    word to the next kept clip). Caveat: a word really said in a pause longer than MAX_PAUSE
    that Whisper dropped entirely is cut with that pause.
    """
    spans = al.times
    before = junk_between(al, asr, float("-inf"), spans[0].start)
    after = junk_between(al, asr, spans[-1].end, float("inf"))
    start = max([spans[0].start - PRE_ROLL, 0.0] + [w["e"] for w in before])
    segs = [Segment(start, 0.0)]
    heard = sorted(al.heard) or range(len(spans))
    for i, j in zip(heard, heard[1:]):
        a, b = spans[i], spans[j]
        junk = junk_between(al, asr, a.end, b.start)
        if b.start - a.end > MAX_PAUSE or junk:
            cut_from = min([a.end + PAD_AFTER] + [w["s"] for w in junk])
            resume = max([b.start - PAD_BEFORE] + [w["e"] for w in junk])
            if resume - cut_from >= MIN_CUT:
                segs[-1].media_out = cut_from
                segs.append(Segment(resume, 0.0))
    segs[-1].media_out = min([take_duration, spans[-1].end + POST_ROLL] + [w["s"] for w in after])
    return [Segment(round(s.media_in, 3), round(s.media_out, 3)) for s in segs]


@lru_cache(maxsize=32)
def _envelope(path: str, stamp: tuple) -> tuple[np.ndarray, float] | None:
    """(20 ms frame levels in dB, voiced threshold) of a take's audio; None when it has no decodable audio."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                              "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    n = int(16000 * SEAM_WIN)
    a = np.frombuffer(raw[: len(raw) // 2 * 2], np.int16).astype(float) / 32768
    if len(a) < 20 * n:
        return None
    db = 10 * np.log10((a[: len(a) // n * n].reshape(-1, n) ** 2).mean(axis=1) + 1e-12)
    return db, float(max(np.percentile(db, 95) - SEAM_DB, np.percentile(db, 10) + 6.0))


def _voiced_edge(db: np.ndarray, thr: float, t: float, step: int) -> float:
    """From the frame at t, walk (step +1 forward / -1 back) while voiced, bridging gaps under SEAM_GAP."""
    k, last, gap = int(t / SEAM_WIN), int(t / SEAM_WIN), 0
    while 0 <= k < len(db) and gap * SEAM_WIN < SEAM_GAP:
        if db[k] > thr:
            last, gap = k, 0
        else:
            gap += 1
        k += step
    return (last + 1) * SEAM_WIN if step > 0 else last * SEAM_WIN


def seam(src, seg: "Segment", first_s: float, last_e: float, head: bool, tail: bool) -> "Segment":
    """Tighten a kept segment where it meets another shot: in = voiced onset - SEAM_HEAD (head), out = voiced
    offset + SEAM_TAIL (tail), never cutting into the first / last word nor widening the segment. Takes with no
    readable audio (test stubs, slots) keep their segment."""
    try:
        st = os.stat(src)
    except OSError:
        return seg
    env = _envelope(str(src), (st.st_mtime_ns, st.st_size)) if head or tail else None
    if env is None:
        return seg
    db, thr = env
    a, b = seg.media_in, seg.media_out
    if head:
        a = max(a, min(first_s - 0.03, _voiced_edge(db, thr, first_s + SEAM_WIN, -1) - SEAM_HEAD))
    if tail:
        b = min(b, max(last_e + 0.03, _voiced_edge(db, thr, max(last_e - SEAM_WIN, 0.0), 1) + SEAM_TAIL))
    return Segment(round(a, 3), round(b, 3)) if b - a > 0.1 else seg


@dataclass
class TakeScore:
    score: float
    coverage: float
    misread: int
    junk_words: int
    cuts: int
    kept: float

    def describe(self) -> str:
        return (f"score {self.score:5.1f}  matched {self.coverage:.0%}  misread {self.misread}  "
                f"junk {self.junk_words}  cuts {self.cuts}  kept {self.kept:.2f}s")


def score_take(al: Alignment, asr: list[dict], segs: list[Segment]) -> TakeScore:
    """Accuracy dominates; fewer cuts and a tighter read break ties.

    A missing or misread word costs far more than a filler, because fillers are cut
    out while a wrong word stays in the reel.
    """
    junk = len(asr) - len(al.used_asr) - len(al.ignored - al.used_asr)   # a hallucination isn't the creator's
    cuts = len(segs) - 1
    kept = sum(s.duration for s in segs)
    score = 100 * al.coverage - 8 * al.misread - 0.5 * junk - 1.0 * cuts - 0.5 * kept
    return TakeScore(round(score, 2), al.coverage, al.misread, junk, cuts, round(kept, 3))


def snap_to_speech(words: list[dict], speech: list[tuple[float, float]]) -> list[dict]:
    """Clamp each word to the VAD speech region it overlaps most.

    Whisper stretches words over neighbouring pauses ("Most" spanning 0.0-1.16 s when speech
    starts at 0.7 s; "and" starting before a pause it is actually said after), which would
    keep dead air and hide pauses from the cutter. Words with no speech overlap keep their
    times and get "speech": False: Whisper writes text over silence (often the line's end again,
    or "Thank you."), and timing.align uses such words only if the voiced ones can't do the job.
    """
    out = []
    for w in words:
        s, e = w["s"], w["e"]
        w = {k: v for k, v in w.items() if k != "speech"}
        best = max(speech, key=lambda r: min(e, r[1]) - max(s, r[0]), default=None)
        if best and min(e, best[1]) - max(s, best[0]) > 0:
            s, e = max(s, best[0]), min(e, best[1])
        elif speech:
            w["speech"] = False
        out.append({**w, "s": round(s, 3), "e": round(e, 3)})
    return out
