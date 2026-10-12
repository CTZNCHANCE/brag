"""Fit returned Suno (or any) tracks to the edit, preview them on the real video, and accept one.

usage: python3 fit_music.py <output_dir>              fit + preview everything in suno/incoming/
       python3 fit_music.py <output_dir> --accept N   put option N into the composition (then run finish.py)

For each track: detect beats (`hyperframes beats`), choose the start offset that lands the strongest
downbeat (with a busy, non-silent window) on the edit's main hit, trim to the video length with a short
fade-in and a 0.9s fade-out, match the original music's level, then apply the composition's existing ducking
and mix with the dialogue + sfx stems onto the real video (picture stream-copied):
  suno/fitted/option-N.wav      trimmed, level-matched, un-ducked (what goes into the composition)
  suno/previews/option-N.mp4    the actual video with this music, at social loudness, to watch and compare
  suno/previews/options.md      offset, hit-beat strength, tempo and loudness per option
"""
import argparse, glob, json, os, re, shutil, statistics, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pro_common import Comp, bass_js, beats, duration, lufs, peak_db, volume_expr  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("output_dir")
ap.add_argument("--accept", type=int)
a = ap.parse_args()

C = Comp(a.output_dir)
S = os.path.join(C.od, "suno")
timing_path = os.path.join(S, "timing.json")
if not os.path.exists(timing_path):
    raise SystemExit("suno/timing.json missing: run suno_prompt.py first")
timing = json.load(open(timing_path))
hit, total = timing["hit"], C.total
music = next(c for c in C.audio() if C.stem_of(c) == "music")
fitted_dir, prev_dir = os.path.join(S, "fitted"), os.path.join(S, "previews")

if a.accept:
    src = os.path.join(fitted_dir, f"option-{a.accept}.wav")
    if not os.path.exists(src):
        raise SystemExit(f"{src} not found: run fit_music.py without --accept first")
    rel = f"assets/music/suno-option-{a.accept}.wav"
    shutil.copy(src, os.path.join(C.dir, rel))
    C.src = C.src.replace(f'src="{music["src"]}"', f'src="{rel}"', 1)
    C.set_attrs(music["id"], data_start=0.0, data_duration=total)
    C.save()
    if "audio-bass.js" in C.src:
        bass_js(src, os.path.join(C.dir, "assets", "audio-bass.js"), C.fps, total)
    json.dump({"accepted": a.accept, "file": rel}, open(os.path.join(S, "accepted.json"), "w"))
    print(f"option {a.accept} is now the music ({rel}). Run finish.py to re-render and re-export.")
    sys.exit(0)

tracks = sorted(f for f in glob.glob(os.path.join(S, "incoming", "*")) if re.search(r"\.(mp3|wav|m4a|aiff?|flac|ogg)$", f, re.I))
if not tracks:
    raise SystemExit("no tracks in suno/incoming/")
os.makedirs(fitted_dir, exist_ok=True)
os.makedirs(prev_dir, exist_ok=True)
orig_music = os.path.join(C.dir, music["src"])
ref_lufs = lufs(orig_music, 0, total)
stems = os.path.join(C.od, "stems")
lane = music["auto"]["lanes"][0]["points"] if music["auto"] else [{"t": 0, "v": 1}]
rows = []

for n, tr in enumerate(tracks, 1):
    D = duration(tr)
    b = beats(tr, S)
    if not b:
        rows.append((n, os.path.basename(tr), "no beats found")); continue
    strengths = sorted(s for _, s in b)
    thr = strengths[int(len(strengths) * 0.8)]
    iv = [y[0] - x[0] for x, y in zip(b, b[1:]) if 0.2 < y[0] - x[0] < 1.6]
    bpm = 60 / statistics.median(iv) if iv else 0
    while bpm > 140: bpm /= 2
    cands = [(t, s) for t, s in b if s >= thr and t - hit >= 0 and t - hit + total <= D]
    if not cands:
        rows.append((n, os.path.basename(tr), f"too short ({D:.1f}s) to place the hit at {hit:.2f}s")); continue
    cands = sorted(cands, key=lambda x: -x[1])[:10]
    best = None
    for t, s in cands:
        off = t - hit
        win = lufs(tr, off, total)
        head = lufs(tr, off, min(1.5, total))
        score = s / max(strengths[-1], 1e-6) + 0.03 * (win + 40) - (0.5 if head < -35 else 0)
        if best is None or score > best[0]:
            best = (score, off, t, s, win)
    _, off, t_hit, s_hit, win = best
    gain = ref_lufs - win
    gain = min(gain, -peak_db(tr) - 1.0)          # never push the bed into clipping
    fit = os.path.join(fitted_dir, f"option-{n}.wav")
    fade_in = "afade=t=in:d=0.08," if off > 0.05 else ""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{off:.3f}", "-t", f"{total:.3f}", "-i", tr, "-af",
                    f"aresample=48000,{fade_in}volume={gain:.2f}dB,afade=t=out:st={max(total - 0.9, 0):.3f}:d=0.9",
                    "-ac", "2", "-c:a", "pcm_s24le", fit], check=True)
    # preview: same ducking + volume as the composition, mixed with the dialogue and sfx stems, on the real picture
    bed = f"[0:a]volume='{volume_expr(lane)}':eval=frame,volume={music['vol']}[m]"
    ins, mixl = [fit], "[m]"
    for k, f in enumerate(("dialogue.wav", "sfx.wav"), 1):
        p = os.path.join(stems, f)
        if os.path.exists(p):
            ins.append(p); mixl += f"[{len(ins) - 1}:a]"
    vid = os.path.join(C.od, "brag.prenorm.mp4") if os.path.exists(os.path.join(C.od, "brag.prenorm.mp4")) else os.path.join(C.od, "brag.mp4")
    cmd = ["ffmpeg", "-loglevel", "error", "-y"] + sum([["-i", p] for p in ins], []) + ["-i", vid,
           "-filter_complex", f"{bed};{mixl}amix=inputs={len(ins)}:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
           "-map", f"{len(ins)}:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-shortest", "-movflags", "+faststart", os.path.join(prev_dir, f"option-{n}.mp4")]
    subprocess.run(cmd, check=True)
    rows.append((n, os.path.basename(tr), f"offset {off:.2f}s · hit beat {t_hit:.2f}s (strength {s_hit:.2f}) · "
                 f"~{bpm:.0f} BPM · window {win:.1f} LUFS → gain {gain:+.1f} dB"))

md = "# Music options\n\n| # | Track | Fit |\n|---|---|---|\n" + "\n".join(f"| {n} | {name} | {info} |" for n, name, info in rows)
md += f"\n\nEach preview is the real video with that track ducked under the narration, main hit on {hit:.2f}s.\n" \
      "Accept one: `fit_music.py <dir> --accept N`, then `finish.py <dir>`. None right? Create again in Suno and drop the new files in incoming/.\n"
open(os.path.join(prev_dir, "options.md"), "w").write(md)
print(md)
