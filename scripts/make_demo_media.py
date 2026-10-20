"""Generate demo media: synthesized SFX + music bed, and fake takes read with macOS `say`.

The takes deliberately differ from the script's estimated pace (slower voice, a lead-in
pause, a filler and a restart) so the demo shows the edit re-timing itself.

Run: .venv/bin/python scripts/make_demo_media.py
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "examples" / "demo" / "media"
TAKES = ROOT / "work" / "demo" / "takes"

READS = {   # several takes per shot, each flawed the way real reads are
    "hook": ["Most creators waste three days editing one reel.",                       # misread
             "Most creators waste three hours, [[slnc 1200]] uh, editing one reel."],  # pause + filler
    "turn": ["Um, what if the edit was, what if the edit was finished before you even pressed record?"],
    "cta": ["Read the script, hit record, [[slnc 900]] and the reel builds itself."],
}
TINTS = {"hook": "0x2b1f4a", "turn": "0x1f3a4a", "cta": "0x4a2b1f"}


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)
    TAKES.mkdir(parents=True, exist_ok=True)

    ff("-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.5", "-af",
       "highpass=f=600,lowpass=f=5000,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.15", str(MEDIA / "whoosh.wav"))
    ff("-f", "lavfi", "-i", "sine=f=880:d=0.12", "-af", "afade=t=out:st=0.02:d=0.1,volume=0.6",
       str(MEDIA / "pop.wav"))
    # 100 BPM bed: soft kick-ish thump on each beat over a low drone.
    ff("-f", "lavfi", "-i", "sine=f=55:d=0.18", "-af", "afade=t=out:st=0.02:d=0.16,apad=pad_dur=0.42",
       "-t", "0.6", str(MEDIA / "_beat.wav"))
    ff("-stream_loop", "40", "-i", str(MEDIA / "_beat.wav"), "-f", "lavfi", "-i", "sine=f=110:d=24",
       "-filter_complex", "[1]volume=0.12[d];[0][d]amix=inputs=2:duration=shortest", "-t", "24",
       str(MEDIA / "bed.wav"))
    (MEDIA / "_beat.wav").unlink()

    takes = {}
    for sid, reads in READS.items():
        takes[sid] = []
        for k, text in enumerate(reads, 1):
            aiff = TAKES / f"{sid}-{k}.aiff"
            subprocess.run(["say", "-r", "150", "-o", str(aiff), "[[slnc 700]] " + text + " [[slnc 600]]"],
                           check=True)
            mp4 = TAKES / f"{sid}-{k}.mp4"
            # Room hum + hiss under the voice, so denoise has something to remove.
            ff("-f", "lavfi", "-i", f"gradients=s=1080x1920:r=30:c0={TINTS[sid]}:c1=0x0b0b0f:speed=0.02",
               "-i", str(aiff), "-f", "lavfi", "-i", "anoisesrc=c=brown:a=0.02",
               "-f", "lavfi", "-i", "sine=f=60",
               "-filter_complex", "[1]aresample=48000[v];[3]volume=0.01[h];[v][2][h]amix=inputs=3:duration=first:normalize=0[a]",
               "-map", "0:v", "-map", "[a]", "-shortest", "-c:v", "libx264", "-crf", "30", "-g", "30", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", "48000", str(mp4))
            aiff.unlink()
            takes[sid].append({"src": mp4.name})
    (TAKES / "takes.json").write_text(json.dumps(takes, indent=2))
    print(f"media -> {MEDIA}\ntakes -> {TAKES}")


if __name__ == "__main__":
    main()
