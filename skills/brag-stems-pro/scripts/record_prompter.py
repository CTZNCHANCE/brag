"""Recording teleprompter: the read-along talent records to, with pre-roll and per-line cues.

usage: python3 record_prompter.py <output_dir> [--preroll 5] [--rehearsal] [--render]

Needs stems/ from brag-stems (transcript.json, music.wav, sfx.wav). Builds <output_dir>/teleprompter-record/
and, with --render, stems/teleprompter-record.mp4:

  * pre-roll: big 5-4-3-2-1 countdown, three beeps on 3-2-1, silence on the downbeat (program 00:00:00:00)
  * running program timecode (negative during pre-roll) and "NEXT LINE IN 2.4s" / "READ" status
  * per line: a cue bar fills during the 1.5s before the line; words light up on their estimated timing
  * guide audio = the music + sfx bed only (no synthetic voice to bleed into the mic);
    --rehearsal adds the original narration at -12 dB for practice runs
Also writes stems/recording-guide.txt for the talent / engineer.
"""
import argparse, glob, html, json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pro_common import HF  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("output_dir")
ap.add_argument("--preroll", type=float, default=5.0)
ap.add_argument("--rehearsal", action="store_true")
ap.add_argument("--render", action="store_true")
a = ap.parse_args()

od = os.path.abspath(a.output_dir)
stems = os.path.join(od, "stems")
tj = os.path.join(stems, "transcript.json")
if not os.path.exists(tj):
    raise SystemExit("stems/transcript.json missing: run brag-stems (export_stems.py, then teleprompter.py) first")
T = json.load(open(tj))
lines, fps, total, PRE = T["lines"], T["fps"], T["duration"], a.preroll
DUR = round(PRE + total + 1.0, 3)
name = "teleprompter-rehearsal" if a.rehearsal else "teleprompter-record"
tp = os.path.join(od, name)
os.makedirs(os.path.join(tp, "assets"), exist_ok=True)


def tc(t):
    neg = t < 0
    f = int(round(abs(t) * fps))
    s = f"{f // (3600 * fps):02d}:{f // (60 * fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"
    return ("-" if neg else "") + s


# guide bed: music + sfx (+ narration at -12 dB in rehearsal mode), delayed by the pre-roll; plus a 1 kHz beep
ins = [os.path.join(stems, f) for f in ("music.wav", "sfx.wav")]
if a.rehearsal:
    ins.append(os.path.join(stems, "dialogue.wav"))
ins = [p for p in ins if os.path.exists(p)]
cmd = ["ffmpeg", "-loglevel", "error", "-y"]
for p in ins:
    cmd += ["-i", p]
chains = [f"[{i}:a]{'volume=-12dB,' if a.rehearsal and p.endswith('dialogue.wav') else ''}anull[s{i}]" for i, p in enumerate(ins)]
mix = "".join(f"[s{i}]" for i in range(len(ins)))
cmd += ["-filter_complex", ";".join(chains) + f";{mix}amix=inputs={len(ins)}:normalize=0,adelay={int(PRE * 1000)}:all=1,apad,atrim=0:{DUR}[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", "-ar", "48000", os.path.join(tp, "assets", "bed.wav")]
subprocess.run(cmd, check=True)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.12:sample_rate=48000",
                "-af", "volume=-6dB,afade=t=out:st=0.1:d=0.02", os.path.join(tp, "assets", "beep.wav")], check=True)

font_css = ""
comp_fonts = os.path.join(od, "composition", "assets", "fonts")
for pat, fam in (("*inter*.woff2", "Inter"), ("*share-tech*.woff2", "Share Tech Mono")):
    hits = glob.glob(os.path.join(comp_fonts, pat))
    if hits:
        shutil.copy(hits[0], os.path.join(tp, "assets", os.path.basename(hits[0])))
        font_css += f"@font-face {{ font-family: '{fam}'; src: url('assets/{os.path.basename(hits[0])}') format('woff2'); font-weight: 100 900; font-display: block; }}\n"

blocks = []
for i, l in enumerate(lines):
    words = "".join(f'<span class="w" id="w{i}_{j}_{k}">{html.escape(w["w"])}</span> '
                    for j, s in enumerate(l["sentences"]) for k, w in enumerate(s["words"]))
    blocks.append(f'<div class="blk" id="b{i}"><div class="tin"><span class="num">{i + 1}</span>{tc(l["start"])}</div>'
                  f'<div class="txt">{words}</div></div>')

beeps = "\n".join(f'  <audio id="beep{k}" src="assets/beep.wav" data-start="{PRE - k}" data-duration="0.12" '
                  f'data-track-index="{3 + k}" data-volume="1"></audio>' for k in (3, 2, 1) if PRE - k >= 0)
L = [{"start": round(l["start"] + PRE, 3), "end": round(l["end"] + PRE, 3),
      "words": [[f"w{i}_{j}_{k}", round(w["start"] + PRE, 3)] for j, s in enumerate(l["sentences"]) for k, w in enumerate(s["words"])]}
     for i, l in enumerate(lines)]
mode = "REHEARSAL · narration at -12 dB" if a.rehearsal else "RECORD · bed only"

page = f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=1920, height=1080" />
<title>Recording prompter — {html.escape(T['title'])}</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{font_css}
html, body {{ margin: 0; background: #000; }}
#root {{ position: relative; width: 1920px; height: 1080px; overflow: hidden; background: #000; color: #f4f4f5; font-family: 'Inter', sans-serif; }}
.mono {{ font-family: 'Share Tech Mono', monospace; letter-spacing: 0.08em; }}
.top {{ position: absolute; left: 0; right: 0; top: 0; height: 150px; display: flex; align-items: center; justify-content: space-between; padding: 0 80px; box-sizing: border-box; background: #000; z-index: 3; border-bottom: 2px solid #26262b; }}
#tc {{ font-size: 92px; color: #ffd84d; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.meta {{ text-align: right; font-size: 28px; color: #8b8b93; line-height: 1.5; white-space: nowrap; }}
.meta b {{ color: #f4f4f5; font-weight: 400; }}
#status {{ font-size: 40px; color: #00ff66; }}
.guide {{ position: absolute; left: 0; right: 0; top: 368px; height: 0; border-top: 3px solid rgba(0,255,102,0.55); z-index: 2; }}
.arrow {{ position: absolute; left: 22px; top: 394px; width: 0; height: 0; border-top: 28px solid transparent; border-bottom: 28px solid transparent; border-left: 40px solid #00ff66; z-index: 2; }}
.cuebar {{ position: absolute; left: 0; top: 362px; height: 6px; width: 1920px; z-index: 2; }}
#cue {{ height: 6px; width: 1920px; background: #ffd84d; transform-origin: 0 50%; }}
.view {{ position: absolute; left: 0; right: 0; top: 152px; bottom: 12px; overflow: hidden; }}
.col {{ position: absolute; left: 0; right: 0; top: 0; padding: 0 120px 0 90px; }}
.blk {{ display: flex; gap: 44px; padding: 26px 0 58px; opacity: 0.4; }}
.tin {{ flex: 0 0 auto; width: 290px; font-family: 'Share Tech Mono', monospace; font-size: 36px; line-height: 84px; color: #00ff66; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.tin .num {{ display: inline-block; width: 64px; color: #8b8b93; }}
.txt {{ flex: 1; font-size: 70px; line-height: 84px; font-weight: 600; color: #8b8b93; }}
#count {{ position: absolute; left: 0; right: 0; top: 380px; height: 300px; text-align: center; font-family: 'Share Tech Mono', monospace; font-size: 300px; line-height: 1; color: #ffd84d; z-index: 4; }}
#countbg {{ position: absolute; left: 0; right: 0; top: 152px; bottom: 12px; background: #000; z-index: 4; }}
#countlbl {{ position: absolute; left: 0; right: 0; top: 260px; text-align: center; font-size: 40px; color: #8b8b93; z-index: 5; }}
.bar {{ position: absolute; left: 0; bottom: 0; height: 12px; width: 1920px; background: #1a1a1d; z-index: 3; }}
#fill {{ height: 12px; width: 1920px; background: #00ff66; transform-origin: 0 50%; }}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="{DUR}" data-fps="{fps}">
  <div class="view"><div class="col" id="col" data-layout-allow-overflow>{''.join(blocks)}</div></div>
  <div class="guide"></div><div class="cuebar"><div id="cue"></div></div><div class="arrow" id="arrow"></div>
  <div class="top"><div id="tc" class="mono">{tc(-PRE)}</div>
    <div class="meta mono"><b>{html.escape(T['title'])}</b> · {mode}<br><span id="status">STAND BY</span></div></div>
  <div id="countbg"></div><div id="countlbl" class="mono">PRE-ROLL · RECORDING STARTS ON THE DOWNBEAT AFTER 3 BEEPS</div>
  <div id="count" data-layout-allow-overlap>{"".join(f'<div class="cd" id="cd{k}" style="position:absolute;left:0;right:0;color:{"#ff4d4d" if k <= 3 else "#ffd84d"};opacity:0">{k}</div>' for k in range(int(PRE), 0, -1))}</div>
  <div class="bar"><div id="fill"></div></div>
  <audio id="bed" src="assets/bed.wav" data-start="0" data-duration="{DUR}" data-track-index="2" data-volume="1"></audio>
{beeps}
</div>
<script>
(function () {{
  const L = {json.dumps(L)};
  const FPS = {fps}, DUR = {DUR}, PRE = {PRE}, GUIDE = 380 - 152 - 26, LEAD = 1.5;
  const tl = gsap.timeline({{ paused: true }});
  const pad = n => String(n).padStart(2, "0");
  const tcEl = document.getElementById("tc"), st = document.getElementById("status");
  const clock = {{ t: 0 }};
  tl.to(clock, {{ t: DUR, duration: DUR, ease: "none", onUpdate: function () {{
    const p = clock.t - PRE, f = Math.round(Math.abs(p) * FPS);
    tcEl.textContent = (p < -0.5 / FPS ? "-" : "") + pad(Math.floor(f / (3600 * FPS))) + ":" + pad(Math.floor(f / (60 * FPS)) % 60) + ":" + pad(Math.floor(f / FPS) % 60) + ":" + pad(f % FPS);
    let s = "CLEAR";
    for (let i = 0; i < L.length; i++) {{
      if (clock.t >= L[i].start && clock.t <= L[i].end + 0.2) {{ s = "READ · LINE " + (i + 1) + " / " + L.length; break; }}
      if (clock.t < L[i].start) {{ s = "LINE " + (i + 1) + " IN " + (L[i].start - clock.t).toFixed(1) + "s"; break; }}
    }}
    st.textContent = clock.t < PRE - 3 ? "STAND BY" : s;
  }} }}, 0);
  tl.fromTo("#fill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: DUR, ease: "none" }}, 0);
  tl.set("#cue", {{ scaleX: 0 }}, 0);
  // pre-roll countdown: one number per second, gone on the downbeat
  for (let k = Math.floor(PRE); k >= 1; k--) {{
    tl.set("#cd" + k, {{ opacity: 1 }}, PRE - k);
    tl.set("#cd" + k, {{ opacity: 0 }}, PRE - k + 1);
  }}
  tl.set(["#count", "#countbg", "#countlbl"], {{ opacity: 0 }}, PRE);
  tl.set("#col", {{ y: () => GUIDE - document.getElementById("b0").offsetTop + 260 }}, 0);
  L.forEach(function (l, i) {{
    const b = document.getElementById("b" + i);
    const at = Math.max(l.start - 0.4, PRE);
    if (l.start - LEAD > 0) {{
      tl.fromTo("#cue", {{ scaleX: 0 }}, {{ scaleX: 1, duration: LEAD, ease: "none", immediateRender: false }}, l.start - LEAD);
      tl.set("#cue", {{ scaleX: 0 }}, l.start);
    }}
    tl.to("#col", {{ y: () => GUIDE - b.offsetTop, duration: 0.4, ease: "power2.inOut" }}, Math.max(l.start - 0.4, 0.01));
    tl.to(b, {{ opacity: 1, duration: 0.2 }}, Math.max(l.start - LEAD, 0.01));
    tl.set("#arrow", {{ borderLeftColor: "#ffd84d" }}, l.start);
    tl.set("#arrow", {{ borderLeftColor: "#00ff66" }}, l.end + 0.2);
    l.words.forEach(function (w) {{ tl.set("#" + w[0], {{ color: "#ffffff" }}, w[1]); }});
    if (i + 1 < L.length) tl.to(b, {{ opacity: 0.4, duration: 0.2 }}, Math.max(L[i + 1].start - LEAD, l.end + 0.2));
  }});
  window.__timelines["main"] = tl;
}})();
</script>
</body></html>
"""
open(os.path.join(tp, "index.html"), "w").write(page)

guide = f"""Recording guide: {T['title']}
Program length {total}s @ {fps} fps · {len(lines)} lines · pre-roll {PRE:.0f}s

1. Play {name}.mp4 full screen. Talent wears closed-back headphones (the guide is the music + sfx bed only).
2. Start recording, THEN press play. Keep rolling straight through all {len(lines)} lines in one take.
3. Countdown: three beeps on 3-2-1. Program time 00:00:00:00 is the silent beat after the third beep.
4. Each line: the yellow bar fills 1.5s before your cue, the arrow turns yellow on the cue, words light up at pace.
5. Leave a clear pause between lines (the importer splits the take at the {len(lines) - 1} widest pauses).
   Pickups: record a single line as its own file named after the line (vo3.wav) — see import_voice.py.
6. Bring the take back: drop it in voice-takes/ and run import_voice.py. Each line is placed at its exact slot.

Lines (program timecode in → out):
""" + "\n".join(f"{i + 1:>2}  {tc(l['start'])} → {tc(l['end'])}  {l['text']}" for i, l in enumerate(lines)) + "\n"
if not a.rehearsal:
    open(os.path.join(stems, "recording-guide.txt"), "w").write(guide)
print(f"{name}: composition in {name}/ ({DUR}s incl. {PRE:.0f}s pre-roll)")

if a.render:
    out = os.path.join(stems, name + ".mp4")
    for step in (["check"], ["render", "--quality", "high", "-o", out]):
        r = subprocess.run(HF + step, cwd=tp, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"hyperframes {step[0]} failed:\n" + (r.stdout + r.stderr)[-3000:])
    print(f"rendered: stems/{name}.mp4")
