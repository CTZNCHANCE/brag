"""Bring a real voiceover take back into the brag composition, each line on its exact slot.

usage: python3 import_voice.py <output_dir> [<take.wav | folder>] [--talent "Name"] [--max-stretch 1.12] [--dry-run]

Input (default <output_dir>/voice-takes/):
  * one continuous take (recorded against teleprompter-record.mp4, or any read with pauses between lines):
    split at the N-1 widest pauses into N lines, in script order;
  * and/or per-line files named after the clip id (vo3.wav, vo3-take2.wav …): these override the split
    for that line (pickups). The newest file per id wins.

Placement: each line's speech starts exactly where the original line's speech started (stems/transcript.json).
If a read is longer than its slot (until the next line), it is time-compressed up to --max-stretch
(pitch preserved, atempo); beyond that it is left long and flagged. A single take-wide gain matches the
original dialogue loudness: no compression, no per-line levelling.

Writes composition/assets/vo/<id>.wav (originals backed up once to assets/vo-synthetic/), updates the
<audio> timings, rebuilds the music ducking from the new line times, and records the talent in script.json.
Then run finish.py to re-render, normalize, and re-export stems/transcript/teleprompters.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pro_common import Comp, duck_lane, duration, group_regions, lane_levels, lufs, speech_regions  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("output_dir")
ap.add_argument("take", nargs="?")
ap.add_argument("--talent", default="")
ap.add_argument("--max-stretch", type=float, default=1.12)
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

C = Comp(a.output_dir)
# the slots are the ORIGINAL narration timings, saved once, so re-imports and pickups never drift
slots_path = os.path.join(C.dir, "assets", "vo-synthetic", "slots.json")
if not os.path.exists(slots_path):
    os.makedirs(os.path.dirname(slots_path), exist_ok=True)
    shutil.copy(os.path.join(C.od, "stems", "transcript.json"), slots_path)
T = json.load(open(slots_path))
lines = T["lines"]
ids = [l["id"] for l in lines]
src = os.path.abspath(a.take or os.path.join(C.od, "voice-takes"))
files = [src] if os.path.isfile(src) else sorted(glob.glob(os.path.join(src, "*.wav")) + glob.glob(os.path.join(src, "*.aif*"))
                                               + glob.glob(os.path.join(src, "*.mp3")) + glob.glob(os.path.join(src, "*.m4a"))
                                               + glob.glob(os.path.join(src, "*.flac")), key=os.path.getmtime)
if not files:
    raise SystemExit(f"no takes found in {src}")
work = os.path.join(C.od, "voice-takes", "_work")
os.makedirs(work, exist_ok=True)

# ---- 1. collect one raw segment per line: (file, start, end)
seg = {}
per_line = {}
for f in files:
    m = re.match(r"(vo\d+)\b", os.path.basename(f).lower())
    if m and m.group(1) in ids:
        per_line[m.group(1)] = f          # newest wins (files sorted by mtime)
full = [f for f in files if f not in per_line.values()]
if full:
    take = full[-1]
    groups = group_regions(speech_regions(take), len(ids))
    if groups is None and not per_line:
        raise SystemExit(f"{os.path.basename(take)}: found fewer speech regions than the {len(ids)} script lines. "
                         "Leave clear pauses between lines, or record pickups as vo<N>.wav files.")
    if groups:
        for cid, (s, e) in zip(ids, groups):
            seg[cid] = (take, s, e)
for cid, f in per_line.items():
    r = speech_regions(f)
    seg[cid] = (f, r[0][0], r[-1][1]) if r else (f, 0.0, duration(f))
missing = [c for c in ids if c not in seg]
if missing:
    raise SystemExit(f"no audio for {', '.join(missing)}: add pickups named {missing[0]}.wav etc.")

# ---- 2. take-wide gain to match the original dialogue stem
orig_dlg = os.path.join(C.od, "stems", "dialogue.wav")
cut = []
for cid in ids:
    f, s, e = seg[cid]
    out = os.path.join(work, f"{cid}.raw.wav")
    s0 = max(s - 0.06, 0.0)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{s0:.3f}", "-t", f"{e - s0 + 0.12:.3f}", "-i", f,
                    "-af", "aresample=48000,afade=t=in:d=0.02", "-ac", "2", "-c:a", "pcm_s24le", out], check=True)
    cut.append(out)
cat = os.path.join(work, "all.wav")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y"] + sum([["-i", p] for p in cut], []) +
               ["-filter_complex", "".join(f"[{i}:a]" for i in range(len(cut))) + f"concat=n={len(cut)}:v=0:a=1", cat], check=True)
gain = (lufs(orig_dlg) - lufs(cat)) if os.path.exists(orig_dlg) else 0.0
gain = max(min(gain, 18.0), -18.0)

# ---- 3. place each line on its slot
clips = {c["id"]: c for c in C.audio()}
new_spans, report = [], []
for i, cid in enumerate(ids):
    line = lines[i]
    slot_start = line["start"]
    slot_end = (lines[i + 1]["start"] - 0.12) if i + 1 < len(lines) else C.total - 0.3
    raw = cut[i]
    d = duration(raw)
    lead = 0.06
    avail = slot_end - (slot_start - lead)
    tempo = 1.0
    if d > avail:
        tempo = min(d / avail, a.max_stretch)
    final = os.path.join(work, f"{cid}.wav")
    af = f"volume={gain:.2f}dB" + (f",atempo={tempo:.4f}" if tempo > 1.0001 else "")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-af", af, "-c:a", "pcm_s24le", "-ar", "48000", final], check=True)
    fd = duration(final)
    # measure the speech onset the same way the transcript does, so the read lands on the exact frame
    onset = (speech_regions(final, noise="-35dB", min_sil=0.12) or [(lead, fd)])[0][0]
    start = max(slot_start - onset, 0.0)
    over = start + fd - slot_end
    flag = "  ⚠ runs %.2fs into the next line" % over if over > 0.05 else ""
    report.append(f"{cid}: {seg[cid][2] - seg[cid][1]:.2f}s read → slot {slot_start:.2f}s"
                  f"{f', sped {tempo:.2f}x' if tempo > 1.0001 else ''}{flag}")
    new_spans.append((start + onset, start + fd - 0.12))
    if not a.dry_run:
        clip = clips[cid]
        dest = os.path.join(C.dir, clip["src"])
        backup = os.path.join(C.dir, "assets", "vo-synthetic")
        if not os.path.exists(os.path.join(backup, os.path.basename(dest))) and os.path.exists(dest):
            os.makedirs(backup, exist_ok=True)
            shutil.copy(dest, os.path.join(backup, os.path.basename(dest)))
        shutil.copy(final, dest)
        # a read that spills into the next slot goes on an alternate track so the clips don't collide
        track = (3 if i % 2 == 0 else 4) if over > 0.05 else (clip["track"] or 3)
        C.set_attrs(cid, data_start=round(start, 3), data_duration=round(fd, 3), data_track_index=track)

print(f"take gain {gain:+.1f} dB to match the original narration level")
print("\n".join(report))
if a.dry_run:
    print("dry run: nothing written"); sys.exit(0)

# ---- 4. music ducking follows the new reads
for c in C.audio():
    if C.stem_of(c) == "music" and c["auto"]:
        base, duck = lane_levels(c["auto"])
        C.set_attrs(c["id"], automation=duck_lane(new_spans, C.total, base, duck))
C.save()
sp = os.path.join(C.dir, "assets", "vo", "script.json")
if os.path.exists(sp):
    s = json.load(open(sp))
    s.setdefault("synthetic_voice", s.get("voice"))
    s["voice"] = a.talent or "Talent take"
    json.dump(s, open(sp, "w"), indent=1, ensure_ascii=False)
print("composition updated. If the talent changed any words, edit composition/assets/vo/script.json, then run finish.py.")
