"""Week 0 smoke test: synth a take, clean it, find speech, get word timestamps, diff vs script.

Run: .venv/bin/python scripts/smoke_test.py
"""
import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work" / "smoke"
WORK.mkdir(parents=True, exist_ok=True)

SCRIPT = "Most creators waste three hours editing one reel. Here is how to get it done in ten minutes."
# The "take" includes a filler and a restart, like a real read.
SPOKEN = "Most creators waste three hours editing one reel. Um, here is, here is how to get it done in ten minutes."
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def words(text):
    return re.findall(r"[a-z']+", text.lower())


def main():
    raw, clean = WORK / "take_raw.wav", WORK / "take_clean.wav"

    t = time.time()
    run(["say", "-o", str(WORK / "take.aiff"), SPOKEN])
    run(["ffmpeg", "-y", "-i", str(WORK / "take.aiff"), "-ar", "48000", "-ac", "1", str(raw)])
    run(["ffmpeg", "-y", "-i", str(raw), "-af", "afftdn=nf=-25,loudnorm=I=-14:TP=-1.5:LRA=11",
         "-ar", "48000", str(clean)])
    print(f"[ok] synth + denoise + loudnorm  {time.time() - t:.1f}s")

    # Whisper runs before torch is imported: loading torch first crashes MLX silently.
    import mlx_whisper
    t = time.time()
    result = mlx_whisper.transcribe(str(clean), path_or_hf_repo=WHISPER_MODEL, word_timestamps=True)
    asr = [w for seg in result["segments"] for w in seg["words"]]
    print(f"[ok] mlx-whisper turbo: {len(asr)} words  {time.time() - t:.1f}s")
    for w in asr:
        print(f"     {w['start']:6.2f}-{w['end']:6.2f}  {w['word'].strip()}")

    import soundfile as sf
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    t = time.time()
    vad_wav = WORK / "take_16k.wav"
    run(["ffmpeg", "-y", "-i", str(clean), "-ar", "16000", "-ac", "1", str(vad_wav)])
    audio, _ = sf.read(vad_wav, dtype="float32")
    speech = get_speech_timestamps(torch.from_numpy(audio), load_silero_vad(), return_seconds=True)
    print(f"[ok] silero VAD: {len(speech)} speech span(s) {speech}  {time.time() - t:.1f}s")

    heard = [re.sub(r"[^a-z']", "", w["word"].lower()) for w in asr]
    ops = difflib.SequenceMatcher(a=words(SCRIPT), b=heard, autojunk=False).get_opcodes()
    extras = [(tag, heard[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
    print(f"[ok] script diff (non-matching spans = fillers/restarts/misreads): {extras}")

    (WORK / "words.json").write_text(json.dumps(asr, indent=2))
    print(f"wrote {WORK / 'words.json'}")


if __name__ == "__main__":
    sys.exit(main())
