"""Mode A sound: mixdown (voice bake, bed, duck, SFX, master) and the audio.py fixes (take leveling,
afftdn delay, adaptive denoise, master/deliver). Synthetic signals only; ffmpeg is used, no mic/camera."""
import json
import subprocess

import numpy as np
import pytest
import soundfile as sf

from reel_director import audio, mixdown
from reel_director.levels import limiter, lufs, master, true_peak_db
from reel_director.schema import Cue, parse_script
from reel_director.timeline import Clip, ShotPlacement, Take, Timeline
from reel_director.timing import Span

SR = 48000
HAS_PACK = (mixdown.PACK / "music" / "manifest.json").exists() and (mixdown.PACK / "sfx" / "manifest.json").exists()


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def tone(sec, f=440.0, amp=0.3):
    t = np.arange(int(sec * SR)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def speechlike(sec, seed=0):
    """Syllable-modulated harmonic tone over a -60 dBFS noise floor (deterministic)."""
    t = np.arange(int(sec * SR)) / SR
    rng = np.random.default_rng(seed)
    v = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 8)) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2
    return 0.2 * v + 0.001 * rng.standard_normal(len(t))


def timeline(tmp_path, take_audio, clips, words, music=False, cues=(), line="one two three four", title="t"):
    wav = tmp_path / "take.wav"
    sf.write(wav, take_audio, SR, subtype="FLOAT")
    s = parse_script({"title": title, "shots": [{"id": "s", "line": line}]}, base_dir=tmp_path)
    s.music = music
    s.shots[0].cues = list(cues)
    end = clips[-1].out_start + clips[-1].duration
    return Timeline(s, [ShotPlacement(s.shots[0], 0.0, end, Take(wav, [], len(take_audio) / SR), clips, words)])


# ---------------------------------------------------------------------------------------------- meter / dynamics
def test_lufs_matches_bs1770_reference_sine():
    x = tone(3.0, 997.0, 0.1)
    assert lufs(np.stack([x, x], 1)) == pytest.approx(-20.0, abs=0.1)


def test_limiter_holds_true_peak_ceiling():
    rng = np.random.default_rng(1)
    x = 0.2 * rng.standard_normal((SR * 2, 2))
    x[SR // 2:SR // 2 + 200] *= 8.0              # hot transient, +12 dB over the body
    y, g = limiter(x, -2.0)
    assert true_peak_db(y) <= -1.95
    assert g.max() <= 1.0 and g.min() > 0.0


def test_master_lands_target_after_limiter():
    rng = np.random.default_rng(2)
    x = 0.05 * rng.standard_normal((SR * 3, 2))
    y, G, _ = master(x, -14.0, -2.0)
    assert lufs(y) == pytest.approx(-14.0, abs=0.05) and true_peak_db(y) <= -1.95


# ---------------------------------------------------------------------------------------------- voice
def test_voice_clips_are_sample_exact_with_fades(tmp_path):
    take = tone(3.0)
    tl = timeline(tmp_path, take, [Clip(0.0, 0.5, 1.2), Clip(0.7, 2.0, 2.6)], [Span(0.1, 0.5), Span(0.8, 1.2)])
    vo, info = mixdown.voice_track(tl, int(1.3 * SR))
    x = vo[:, 0]
    g = x[int(0.25 * SR)] / take[int(0.75 * SR)]       # one shot gain, applied to every sample
    mid = slice(round(0.2 * SR), round(0.3 * SR))         # inside clip 1: media = reel + 0.5
    assert np.allclose(x[mid], g * take[round(0.7 * SR):round(0.8 * SR)], atol=1e-9)
    mid2 = slice(round(0.9 * SR), round(1.0 * SR))        # inside clip 2: media = reel + 1.3
    assert np.allclose(x[mid2], g * take[round(2.2 * SR):round(2.3 * SR)], atol=1e-9)
    assert 20 * np.log10(g) == pytest.approx(info[0]["gain_db"], abs=0.01)
    cut = int(0.7 * SR)
    assert np.abs(np.diff(x[cut - 480:cut + 480])).max() < 0.02    # no step at the jump cut
    assert abs(x[0]) < 1e-3 and np.abs(x[cut - 3:cut + 3]).max() < 0.01


def test_gate_clamps_junk_tail_at_cut_but_not_the_word():
    rng = np.random.default_rng(3)
    seg = 0.001 * rng.standard_normal(int(0.4 * SR))                   # floor -60 dBFS
    seg[:int(0.04 * SR)] += 0.1 * rng.standard_normal(int(0.04 * SR))  # 40 ms junk tail at the cut
    seg[int(0.12 * SR):] += tone(0.28, 300, 0.2)                       # the kept word from 120 ms
    out, notes = mixdown.gate_edges(seg.copy(), 0.12, 0.4, -60.0)
    head = 20 * np.log10(np.sqrt(np.mean(out[:int(0.035 * SR)] ** 2)))
    assert head < -50 and notes and "head" in notes[0]
    assert np.allclose(out[int(0.15 * SR):], seg[int(0.15 * SR):])


def test_shots_are_leveled_on_what_ships(tmp_path):
    loud_junk = np.concatenate([speechlike(1.0) * 3.0, speechlike(2.0, 1)])
    tl = timeline(tmp_path, loud_junk, [Clip(0.0, 1.0, 3.0)], [Span(0.1, 0.9), Span(1.0, 1.9)])
    vo, info = mixdown.voice_track(tl, int(2.0 * SR))
    assert lufs(vo[:, :1]) == pytest.approx(audio.TAKE_LUFS, abs=0.2)


# ---------------------------------------------------------------------------------------------- duck / bed / sfx
def test_duck_curve_attack_ahead_and_release():
    mask = np.zeros(2000, bool)
    mask[500:1500] = True                            # speech 0.5-1.5 s on the 1 ms grid
    w = mixdown.duck_curve(mask, 2 * SR, 12.0)
    at = lambda t: w[int(t * SR)]
    full = 0.5 - mixdown.LOOKAHEAD + mixdown.ATTACK                 # council 9: 80 ms look-ahead, 15 ms attack
    assert at(0.5 - mixdown.LOOKAHEAD - 0.002) == pytest.approx(0.0, abs=1e-6)
    assert at(full + 0.001) == pytest.approx(1.0, abs=1e-6) and at(0.5) == 1.0
    assert at(1.0) == 1.0 and at(1.5 + mixdown.HOLD - 0.002) == 1.0     # 120 ms hold after the word
    assert at(1.5 + mixdown.HOLD + mixdown.RELEASE + 0.01) == pytest.approx(0.0, abs=1e-6)
    assert 0 < at(1.5 + mixdown.HOLD + 0.1) < 1


def test_speech_mask_holds_short_pauses(tmp_path):
    x = np.concatenate([speechlike(0.5), np.zeros(int(0.3 * SR)), speechlike(0.5, 1)])
    tl = timeline(tmp_path, x, [Clip(0.0, 0.0, 1.3)], [Span(0.0, 0.5), Span(0.8, 1.3)])
    m = mixdown.speech_mask(x, tl)
    assert m[100:1200].all()                         # the 0.3 s pause keeps the bed down


def test_bed_choice_is_deterministic_and_optional(tmp_path):
    tl = timeline(tmp_path, tone(1.0), [Clip(0.0, 0.0, 1.0)], [Span(0.1, 0.9)])
    assert mixdown.pick_bed(tl) is None              # music: false
    tl.script.music = {"src": "bed.wav"}
    assert mixdown.pick_bed(tl)["file"].endswith("bed.wav")
    if not HAS_PACK:
        pytest.skip("motion-pack not present")
    tl.script.music = {"mood": "calm"}
    a, b = mixdown.pick_bed(tl), mixdown.pick_bed(tl)
    assert a["id"] == b["id"] and "calm" in a["mood"]
    grid = mixdown.plan_bed(tl)["grid"]
    assert grid["bars"] and min(abs(t - mixdown.hero_time(tl)) for t in grid["bars"]) < 1 / 30


@pytest.mark.skipif(not HAS_PACK, reason="motion-pack not present")
def test_sfx_id_anchor_lands_on_frame_plus_one(tmp_path):
    cue = Cue("sfx", 1, 1, {"id": "snd.ui.pop"})
    tl = timeline(tmp_path, tone(2.0), [Clip(0.0, 0.0, 2.0)], [Span(0.1, 0.4), Span(0.5, 0.9), Span(1.0, 1.4),
                                                                 Span(1.5, 1.9)], cues=[cue])
    ev = mixdown.sfx_events(tl)[0]
    e = mixdown._sfx_entry("snd.ui.pop")
    F = int(np.floor(0.5 * 30 + 0.5))
    assert ev["start"] + e["anchor_sample"] == (F + 1) * SR // 30


def test_mixdown_end_to_end_meets_spec(tmp_path):
    bed = tmp_path / "bed.wav"
    rng = np.random.default_rng(4)
    sf.write(bed, 0.05 * rng.standard_normal((SR * 2, 2)), SR)          # 2 s loop, tiled
    pop = tmp_path / "pop.wav"
    sf.write(pop, tone(0.1, 1500, 0.9) * np.linspace(1, 0, int(0.1 * SR)), SR)
    take = np.concatenate([np.zeros(int(0.3 * SR)), speechlike(1.2), np.zeros(int(0.9 * SR)), speechlike(1.2, 2)])
    words = [Span(0.3, 0.9), Span(0.9, 1.5), Span(2.4, 3.0), Span(3.0, 3.6)]
    tl = timeline(tmp_path, take, [Clip(0.0, 0.0, 3.6)], words, music={"src": "bed.wav"},
                  cues=[Cue("sfx", 2, 2, {"src": "pop.wav"})])
    rep = mixdown.mixdown(tl, tmp_path / "mix.wav")
    y, sr = sf.read(tmp_path / "mix.wav")
    assert sr == SR and y.shape == (int(round(3.6 * SR)), 2)
    assert rep["master"]["lufs"] == pytest.approx(-14.0, abs=0.1)
    assert rep["master"]["aac"]["true_peak"] <= audio.MASTER_TP - 0.05
    assert rep["bed"]["measured"]["duck_depth_db"] >= 10.0
    assert rep["sfx"][0]["cue_loudness_db"] <= rep["voice"]["lufs"]
    assert json.loads((tmp_path / "mix.json").read_text())["duration"] == pytest.approx(3.6)
    assert (tmp_path / "mix.vo.flac").exists() and abs(y[-1]).max() < 1e-4


# ---------------------------------------------------------------------------------------------- audio.py fixes
def pts_steps(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return set(np.diff([int(p["pts"]) for p in json.loads(out)["packets"]]).tolist())


@pytest.fixture(scope="module")
def noisy_take(tmp_path_factory):
    d = tmp_path_factory.mktemp("take")
    src = d / "take.mp4"
    beeps = "+".join(f"between(t\\,{t}\\,{t + 0.25})" for t in (0.5, 1.2, 1.9, 2.6))
    ff("-f", "lavfi", "-i", "color=black:s=64x64:r=30:d=3.5", "-f", "lavfi",
       "-i", f"aevalsrc=0.5*sin(2*PI*440*t)*({beeps}):s=48000:d=3.5", "-f", "lavfi", "-i", "anoisesrc=c=brown:a=0.4:d=3.5:r=48000",
       "-filter_complex", "[1][2]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", str(src))
    return src


def test_clean_take_has_no_pts_gaps_and_no_delay(noisy_take, tmp_path):
    dst = tmp_path / "clean.mp4"
    r = audio.clean_take(noisy_take, dst)
    assert r["denoise"] and 6 <= r["nr_db"] <= 12
    assert pts_steps(dst) == {1024}
    assert r["after_lufs"] == pytest.approx(audio.TAKE_LUFS, abs=0.5) and r["true_peak"] <= -1.0
    a, b = audio.decode(noisy_take, 1)[:, 0], audio.decode(dst, 1)[:, 0]
    c = np.correlate(b[SR:SR + 9600], a[SR - 480:SR + 9600 + 480], mode="valid")
    assert abs(int(np.argmax(c)) - 480) < 48 and len(a) == len(b)


def test_denoise_skips_clean_takes():
    chain, info = audio.denoise_chain(40.0)
    assert "afftdn" not in chain and not info["denoise"]
    chain, info = audio.denoise_chain(20.0)
    assert "afftdn=nr=12" in chain and "atrim=start_sample=1200" in chain


def test_master_and_deliver_meet_spec_without_pts_gaps(noisy_take, tmp_path):
    hot = tmp_path / "mix.wav"
    x = np.concatenate([speechlike(1.5) * 2.5, np.zeros(int(1.5 * SR)), speechlike(0.5, 3) * 4.0])
    sf.write(hot, np.stack([x, x], 1).clip(-1, 1), SR)                 # too loud and peaky
    out = tmp_path / "reel-master.mp4"
    d = audio.deliver(noisy_take, hot, out)
    assert d["ok"] and d["true_peak"] <= audio.MASTER_TP and abs(d["lufs"] - audio.MASTER_LUFS) <= 0.5
    assert d["av_start_offset_ms"] == 0 and pts_steps(out) == {1024}
    m = audio.master(noisy_take, tmp_path / "mastered.mp4")
    assert m["true_peak"] <= audio.MASTER_TP and abs(m["after_lufs"] - audio.MASTER_LUFS) <= 0.5
    assert pts_steps(tmp_path / "mastered.mp4") == {1024}


def test_mixdown_aac_loop_lowers_ceiling_until_encoded_peak_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(mixdown, "WAV_CEIL", -0.3)               # start too hot on purpose
    take = np.concatenate([speechlike(1.5), speechlike(1.5, 5)])
    take[2400::4800] += 0.9                                      # sharp clicks: hot inter-sample peaks after AAC
    tl = timeline(tmp_path, take, [Clip(0.0, 0.0, 3.0)], [Span(0.1, 1.4), Span(1.6, 2.9)])
    rep = mixdown.mixdown(tl, tmp_path / "mix.wav", stems=False)
    assert rep["master"]["ceiling_db"] < -0.3
    assert rep["master"]["aac"]["true_peak"] <= audio.MASTER_TP - 0.05
    assert rep["master"]["aac"]["lufs"] == pytest.approx(-14.0, abs=0.3)
