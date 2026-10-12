"""Write a Suno music prompt + timing sheet that matches the edit, and an incoming/ folder for the results.

usage: python3 suno_prompt.py <output_dir> --style "warm boom-bap, Rhodes, vinyl crackle" [--bpm 110] [--title "..."]

Reads the composition: scene cuts, the outro/logo hit, narration windows (where the music sits under the voice),
and the current music's tempo. Writes <output_dir>/suno/:
  suno-prompt.md   what to paste into Suno (Custom mode), plus a time-coded sheet of the edit's moments
  timing.json      the same moments, machine-readable (fit_music.py uses it)
  incoming/        drop the downloaded Suno tracks here (mp3/wav/m4a), then run fit_music.py
Suno does not follow timestamps; fit_music.py lines the chosen track's strongest beat up with the hit instead.
"""
import argparse, json, os, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pro_common import Comp, beats  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("output_dir")
ap.add_argument("--style", required=True, help="genre / instruments / mood, from the brag plan's tone")
ap.add_argument("--bpm", type=float)
ap.add_argument("--title")
ap.add_argument("--hit", type=float, help="seconds of the main hit (default: start of the last scene)")
a = ap.parse_args()

C = Comp(a.output_dir)
out = os.path.join(C.od, "suno")
os.makedirs(os.path.join(out, "incoming"), exist_ok=True)

# scenes = timed non-audio elements directly in the root
scenes = sorted({float(m.group(1)) for m in re.finditer(
    r'<(?:section|div)\b[^>]*class="[^"]*\bclip\b[^"]*"[^>]*data-start="([\d.]+)"', C.src)})
scenes = scenes or [0.0]
hit = a.hit if a.hit is not None else (scenes[-1] if len(scenes) > 1 else round(C.total * 0.8, 2))
clips = C.audio()
vo = sorted((c["start"], c["start"] + c["dur"]) for c in clips if C.stem_of(c) == "dialogue")
accents = sorted(round(c["start"], 2) for c in clips if C.stem_of(c) == "sfx")

bpm = a.bpm
if not bpm:
    music = [c for c in clips if C.stem_of(c) == "music"]
    try:
        b = beats(os.path.join(C.dir, music[0]["src"]), out) if music else []
        iv = [y[0] - x[0] for x, y in zip(b, b[1:]) if 0.2 < y[0] - x[0] < 1.6]
        bpm = 60 / statistics.median(iv) if iv else 110
        while bpm > 140:
            bpm /= 2
        while bpm < 75:
            bpm *= 2
    except SystemExit:
        bpm = 110
bpm = round(bpm)


def mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


moments = [{"t": 0.0, "what": "Open — first frame", "music": "start strong (no long fade-in); the voice enters at "
            + (mmss(vo[0][0]) if vo else "—")}]
for s in [x for x in scenes[1:] if abs(x - hit) > 0.05]:
    moments.append({"t": s, "what": "Scene cut", "music": "a clear bar or phrase change helps"})
moments.append({"t": hit, "what": "MAIN HIT — logo / outro", "music": "the biggest downbeat of the track: drop, impact or full-band hit"})
moments.append({"t": C.total, "what": "End of video", "music": "can keep going; it is trimmed and faded here"})
moments.sort(key=lambda m: m["t"])

title = a.title or f"{os.path.basename(C.od)} bed"
style = (f"{a.style.strip().rstrip(',')}, instrumental, {bpm} BPM, punchy intro, steady groove, "
         f"one big drop, clean ending")
timing = {"duration": C.total, "bpm_target": bpm, "hit": hit, "scenes": scenes, "narration": vo,
          "sfx_accents": accents, "style": style, "title": title}
json.dump(timing, open(os.path.join(out, "timing.json"), "w"), indent=1)

under = ", ".join(f"{mmss(s)}–{mmss(e)}" for s, e in vo) or "none"
md = f"""# Suno prompt: {title}

Video length **{C.total:.1f}s**, target **{bpm} BPM**, main hit at **{mmss(hit)}**.

## Paste into Suno (Create → Custom)

**Style of Music**
```
{style}
```

**Exclude Styles** (More Options)
```
vocals, singing, rap, spoken word, choir
```

**Instrumental:** on

**Title:** `{title}`

**Lyrics box** (only if your Suno version shows it with Instrumental on; structure tags, no words):
```
[Intro]
[Groove]
[Build]
[Drop]
[Outro]
[End]
```

Press Create once or twice: each Create makes 2 versions, so you'll get 2–4 to choose from. These use your own Suno credits.

## Timing sheet (what the edit needs)

| Time | Edit moment | Music should… |
|---|---|---|
""" + "\n".join(f"| {mmss(m['t'])} | {m['what']} | {m['music']} |" for m in moments) + f"""

Narration sits on top during {under}. Keep those parts sparse: no lead melody fighting the voice.

## Bring the tracks back

1. Download each version (MP3 or WAV) into `suno/incoming/`.
2. Run `fit_music.py`. For each track it finds the beats, picks the strongest downbeat to land on {mmss(hit)}, trims and fades it to {C.total:.1f}s, applies the same ducking, and renders a preview of the real video with the new music: `suno/previews/option-N.mp4`.
3. Watch the previews. Accept one with `fit_music.py --accept N`, or go back to Suno, press Create again, and drop the new versions in.

Suno doesn't follow timestamps; the fitting step does the lining up. The style line is a starting point, so adjust it freely.
Licensing: songs made on Suno's free plan are for non-commercial use. Use a paid plan for ads and client work.
"""
open(os.path.join(out, "suno-prompt.md"), "w").write(md)
print(f"suno/suno-prompt.md + timing.json written ({bpm} BPM, hit {mmss(hit)}); drop tracks in suno/incoming/")
