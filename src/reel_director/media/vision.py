"""Claude vision rerank for media.select.pick (optional): `claude -p` looks at the top thumbnails; its scores blend
50/50 with the metadata score. Cached by query + thumbnail hashes, so a media.json replays without calling Claude.
(Split out of select.py in the v4 final round to keep files under 500 lines; select re-exports these names.)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from typing import Callable

VISION_PROMPT = """You are choosing B-roll for a vertical short-form video. The insert must show: "{query}".
Open each numbered image file below with the Read tool and judge it as a 1.2-3 s full-screen insert.
Score relevance 0-10 (does it clearly show the subject?) and quality 0-10 (sharp, well lit, modern, uncluttered,
works cropped to 9:16). Flag visible text/watermarks/logos and identifiable people's faces.
Reply with ONLY one JSON object, no prose:
{{"scores": [{{"i": 1, "relevance": 0, "quality": 0, "text": false, "faces": false}}]}}
Images:
{images}"""


# Same rule as the claude_clip provider: the child `claude -p` runs on the subscription login, never an API key
# (= never paid), and without this session's variables (a nested session cannot refresh its OAuth token).
STRIP_ENV = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "ANTHROPIC_API_KEY")
STRIP_ENV_PREFIX = ("CLAUDE_CODE_SESSION", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_HOST", "CLAUDE_CODE_MESSAGING",
                    "CLAUDE_CODE_SDK", "CLAUDE_CODE_CHILD", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EXECPATH",
                    "CLAUDE_AGENT_SDK")


def claude_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV and not k.startswith(STRIP_ENV_PREFIX)}
    return {**env, "NO_COLOR": "1"}


def vision_rerank(cache, http=None, top: int = 6, run=subprocess.run, timeout: float = 240,
                  claude: str = "claude") -> Callable:
    """A `vision` hook for pick(): Claude looks at the top thumbnails; blended 50/50 with the metadata score.
    Raises RuntimeError when `claude -p` fails or answers without scores (pick() notes it and keeps metadata order)."""
    from .select import Scored

    def rerank(scored: list, query: str) -> list:
        pool, rest, files = scored[:top], scored[top:], []
        for s in pool:
            try:
                files.append(cache.fetch_url(s.cand.thumb or s.cand.url, http, max_bytes=8 << 20))
            except Exception:       # noqa: BLE001
                files.append(None)
        live = [(i, s, f) for i, (s, f) in enumerate(zip(pool, files)) if f]
        if not live:
            return scored
        key = "vision:v1:" + hashlib.sha256(json.dumps([query, [f.stem for _, _, f in live]]).encode()).hexdigest()
        res = cache.json_get(key, ttl=0)
        if res is None:
            imgs = "\n".join(f"{n + 1}: {f}" for n, (_, _, f) in enumerate(live))
            r = run([claude, "-p", VISION_PROMPT.format(query=query, images=imgs), "--allowedTools", "Read",
                     "--add-dir", str(cache.root)], capture_output=True, text=True, timeout=timeout, env=claude_env())
            res = parse_scores(r.stdout or "")
            if r.returncode or not res:
                err = " ".join(x for x in f"{r.stdout or ''} {r.stderr or ''}".splitlines()
                               if not x.startswith("Permission deny rule"))
                raise RuntimeError(f"claude -p exit {r.returncode}: {err.strip()[-160:] or 'no scores in the answer'}")
            cache.json_put(key, res)
        by_i = {int(x.get("i", 0)): x for x in res or []}
        out = []
        for n, (_, s, _) in enumerate(live):
            v = by_i.get(n + 1)
            if not v:
                out.append(s)
                continue
            vs = (0.65 * float(v.get("relevance", 0)) + 0.35 * float(v.get("quality", 0))) / 10
            vs *= (0.75 if v.get("text") else 1.0) * (0.8 if v.get("faces") else 1.0)
            out.append(Scored(s.cand, 0.5 * s.score + 0.5 * vs, {**s.parts, "vision": v}))
        out += [s for s, f in zip(pool, files) if not f]
        return sorted(out, key=lambda s: (-round(s.score, 6), s.cand.id)) + rest
    return rerank


def parse_scores(text: str) -> list[dict] | None:
    for m in reversed(list(re.finditer(r"\{.*\}", text, re.S))):
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict) and isinstance(d.get("scores"), list):
                return d["scores"]
        except ValueError:
            continue
    return None
