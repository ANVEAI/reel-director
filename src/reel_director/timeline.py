"""Shots -> reel timeline. Picks the best take per shot and maps its kept segments to reel time."""
from dataclasses import dataclass, field
from pathlib import Path

from .cleanup import POST_ROLL, PRE_ROLL, Segment, TakeScore, keep_segments, score_take, seam
from .schema import Script, Shot
from .timing import Span, align, estimate


@dataclass
class Take:
    src: Path
    words: list[dict]
    duration: float
    pin: bool = False     # the creator's choice overrides the score


@dataclass
class Clip:
    """One kept segment of a take, placed in the reel."""
    out_start: float
    media_in: float
    media_out: float

    @property
    def duration(self) -> float:
        return round(self.media_out - self.media_in, 3)


@dataclass
class ShotPlacement:
    shot: Shot
    out_start: float
    duration: float
    take: Take | None                 # None: not recorded yet, a slot is shown
    clips: list[Clip]
    words: list[Span]                 # reel time
    coverage: float = 1.0
    take_index: int | None = None
    scores: list[TakeScore] = field(default_factory=list)   # one per candidate take


@dataclass
class Timeline:
    script: Script
    shots: list[ShotPlacement]

    @property
    def duration(self) -> float:
        last = self.shots[-1]
        return round(last.out_start + last.duration, 3)


def _to_reel(t: float, clips: list[Clip]) -> float:
    """Media time -> reel time. Times inside a cut snap to the next kept clip."""
    for c in clips:
        if t < c.media_out:
            return c.out_start + max(0.0, t - c.media_in)
    last = clips[-1]
    return last.out_start + last.duration


def pick_take(shot: Shot, takes: list[Take]):
    """The pinned take if there is one, else the best-scoring; on a tie the later one wins
    (creators usually improve). Every take is scored either way, for the report."""
    if not takes:
        return None, []
    results = []
    for take in takes:
        al = align(shot, take.words)
        segs = keep_segments(al, take.words, take.duration)
        results.append((al, segs, score_take(al, take.words, segs)))
    scored = [sc for _, _, sc in results]
    pinned = [i for i, t in enumerate(takes) if t.pin]
    best = pinned[-1] if pinned else max(range(len(takes)), key=lambda i: (scored[i].score, i))
    return (best, *results[best]), scored


def build_timeline(script: Script, takes: dict[str, list[Take]] | None = None) -> Timeline:
    """Shots end to end. Where two recorded shots meet, the seam is tightened to the voice (cleanup.seam):
    the reel's first frame and last tail keep PRE_ROLL / POST_ROLL."""
    takes = takes or {}
    t, placed = 0.0, []
    rec = [bool(takes.get(sh.id)) for sh in script.shots]
    for si, shot in enumerate(script.shots):
        candidates = takes.get(shot.id) or []
        if candidates:
            (idx, al, segs, _), scored = pick_take(shot, candidates)
            take, media_spans, coverage = candidates[idx], al.times, al.coverage
            head, tail = si > 0 and rec[si - 1], si + 1 < len(rec) and rec[si + 1]
            segs = list(segs)
            if head:
                segs[0] = seam(take.src, segs[0], media_spans[0].start, media_spans[-1].end, True, False)
            if tail:
                segs[-1] = seam(take.src, segs[-1], media_spans[0].start, media_spans[-1].end, False, True)
        else:
            idx, scored, take, coverage = None, [], None, 1.0
            est = estimate(shot)
            media_spans = [Span(s.start + PRE_ROLL, s.end + PRE_ROLL) for s in est]
            segs = [Segment(0.0, media_spans[-1].end + POST_ROLL)]
        clips, cursor = [], t
        for s in segs:
            clips.append(Clip(round(cursor, 3), s.media_in, s.media_out))
            cursor += s.media_out - s.media_in
        reel = [Span(round(_to_reel(s.start, clips), 3), round(_to_reel(s.end, clips), 3)) for s in media_spans]
        dur = round(cursor - t, 3)
        placed.append(ShotPlacement(shot, round(t, 3), dur, take, clips, reel, coverage, idx, scored))
        t = cursor
    return Timeline(script, placed)
