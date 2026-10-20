"""Loudness and dynamics primitives shared by mixdown and audio: BS.1770 meter, a 4x true-peak
look-ahead limiter, loudness-targeted mastering and an AAC round-trip probe. numpy/scipy only."""
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import lfilter, resample_poly

from .audio import MASTER_LUFS, SR, loudness

WAV_CEIL = -2.0         # first limiter ceiling (dBTP, 4x); mixdown lowers it until the AAC meets the spec

_K1 = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
_K2 = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])


def _st(x) -> np.ndarray:
    x = np.asarray(x, float)
    return x[:, None] if x.ndim == 1 else x


def block_loudness(x, win: float = 0.4, hop: float = 0.1) -> np.ndarray:
    """BS.1770 loudness (LUFS) of each window (K-weighted, channel powers summed)."""
    k = lfilter(*_K2, lfilter(*_K1, _st(x), axis=0), axis=0)
    p = np.sum(k ** 2, axis=1)
    n, h = int(win * SR), max(1, int(hop * SR))
    if len(p) < n:
        return np.array([-0.691 + 10 * np.log10(np.mean(p) + 1e-20)]) if len(p) else np.array([-200.0])
    c = np.concatenate([[0.0], np.cumsum(p)])
    s = np.arange(0, len(p) - n + 1, h)
    return -0.691 + 10 * np.log10((c[s + n] - c[s]) / n + 1e-20)


def lufs(x) -> float:
    """Gated integrated loudness (BS.1770-4: 400 ms blocks, 75 % overlap, -70 / -10 LU gates)."""
    bl = block_loudness(x)
    g = bl > -70
    if not g.any():
        return -70.0
    z = 10 ** ((bl + 0.691) / 10)
    g &= bl > -0.691 + 10 * np.log10(z[g].mean()) - 10
    return float(-0.691 + 10 * np.log10(z[g].mean()))


def true_peak_db(x, os_: int = 4) -> float:
    x = _st(x)
    pk = max(float(np.abs(resample_poly(x[:, c], os_, 1)).max(initial=0)) for c in range(x.shape[1]))
    return 20 * np.log10(max(pk, 1e-12))


# ------------------------------------------------------------------------------------------------ dynamics
def tp_envelope(x) -> np.ndarray:
    """Per-sample true-peak envelope (max of the 4x oversampled points and the sample itself)."""
    x = _st(x)
    up = np.abs(resample_poly(x, 4, 1, axis=0)).max(axis=1)[: len(x) * 4].reshape(-1, 4).max(axis=1)
    return np.maximum(up, np.abs(x).max(axis=1))


def limiter(x, ceiling_db: float, look: float = 0.003, release: float = 0.08, pk=None):
    """True-peak (4x) look-ahead limiter: the gain is down before each peak (3 ms look-ahead, smoothed)
    and recovers exponentially (time constant `release`), run at a 32-sample control rate.
    `pk`: a precomputed tp_envelope(x) (it scales linearly with gain)."""
    x = _st(x)
    pk = tp_envelope(x) if pk is None else pk
    req = np.minimum(1.0, 10 ** (ceiling_db / 20) / np.maximum(pk, 1e-12))
    L, B = max(1, int(look * SR)), 32
    rl = minimum_filter1d(req, 2 * L + 1, mode="nearest")
    m = -(-len(rl) // B)
    rb = np.pad(rl, (0, m * B - len(rl)), constant_values=1.0).reshape(m, B).min(axis=1)
    a, s, gb = float(np.exp(-B / (release * SR))), 1.0, np.empty(m)
    for i, r in enumerate(rb.tolist()):          # instant attack, exponential release toward the requirement
        s = r if r < s else r - (r - s) * a
        gb[i] = s
    g = np.minimum(uniform_filter1d(np.repeat(gb, B)[: len(rl)], L, mode="nearest"), 1.0)
    return x * g[:, None], g


def master(pre, target: float = MASTER_LUFS, ceiling_db: float = WAV_CEIL):
    """Gain so the integrated loudness lands on target AFTER the limiter. Returns (out, gain, curve).

    Loudness vs gain can jump (limited transients drop under the -10 LU relative gate), so this is a
    secant search that turns into bisection once the target is bracketed, keeping the closest result."""
    g0, pk = target - lufs(pre), tp_envelope(pre)
    gdb, lo, hi, best = g0, None, None, None      # steps stay within -20..+12 dB of the plain gain
    for _ in range(14):
        y, g = limiter(pre * 10 ** (gdb / 20), ceiling_db, pk=pk * 10 ** (gdb / 20))
        err = lufs(y) - target
        if best is None or abs(err) < abs(best[0]):
            best = (err, y, 10 ** (gdb / 20), g)
        if abs(err) < 0.03:
            break
        lo, hi = (gdb, hi) if err < 0 else (lo, gdb)
        gdb = (lo + hi) / 2 if lo is not None and hi is not None else float(np.clip(gdb - err, g0 - 20, g0 + 12))
    return best[1], best[2], best[3]


def aac_probe(x) -> dict:
    """Encode exactly as audio.deliver does, decode, measure (ffmpeg ebur128 + own 4x true peak)."""
    with tempfile.TemporaryDirectory() as td:
        w, m = Path(td) / "a.wav", Path(td) / "a.m4a"
        sf.write(w, np.asarray(x, np.float32), SR, subtype="FLOAT")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(w), "-c:a", "aac", "-b:a", "256k", "-ar", str(SR),
                        str(m)], check=True, capture_output=True)
        meas = loudness(m)
        y = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(m), "-f", "f32le", "-ac", "2", "-"],
                                         check=True, capture_output=True).stdout, "<f4").reshape(-1, 2)
    return {"lufs": meas["I"], "true_peak": max(meas["tp"], round(true_peak_db(y), 2))}
