"""Bring a rendered brag video up to social-platform loudness without touching the picture.

usage: python3 normalize_video.py <video.mp4> [--lufs -14] [--tp -1.5]

FFmpeg loudnorm (EBU R128, single pass), aiming at about -14 LUFS with a true-peak ceiling.
Peaky mixes (big SFX hits) land a little under the target instead of being squashed;
the ceiling leaves headroom for AAC encoding.
The video stream is stream-copied, so a baked poster frame 0 survives.
The file is replaced in place; the original is kept as <name>.prenorm.mp4.
Run this before export_stems.py: mix.wav then matches the posted video,
and the stems stay unprocessed.
"""
import argparse, os, re, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--lufs", type=float, default=-14.0)
ap.add_argument("--tp", type=float, default=-1.5)
a = ap.parse_args()


def measure(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    i = re.findall(r"^\s+I:\s+(-?[\d.]+) LUFS", r, re.M)
    p = re.findall(r"^\s+Peak:\s+(-?[\d.]+|-inf) dBFS", r, re.M)
    return (i[-1] if i else "?"), (p[-1] if p else "?")


# Apple's AAC encoder when present (macOS); FFmpeg's native one can add a start-of-file peak on loud mixes
enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
codec = "aac_at" if re.search(r"^\s*A\S*\s+aac_at\b", enc, re.M) else "aac"

base, ext = os.path.splitext(a.video)
orig = base + ".prenorm" + ext
tmp = base + ".norm" + ext
os.replace(a.video, orig)
before, _ = measure(orig)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", orig, "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-af", f"loudnorm=I={a.lufs}:TP={a.tp}:LRA=11",
                "-c:a", codec, "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", tmp], check=True)
os.replace(tmp, a.video)
after, peak = measure(a.video)
print(f"loudness: {before} → {after} LUFS (true peak {peak} dBFS, {codec}); original kept as {orig}")
