"""Shared helpers for the brag-stems-pro scripts (standard library + ffmpeg only)."""
import html, json, os, re, subprocess

HF = ["npx", "-y", os.environ.get("HYPERFRAMES_PKG", "hyperframes@0.8.143")]
HERE = os.path.dirname(os.path.abspath(__file__))


def stems_scripts():
    """Locate the sibling brag-stems scripts (plugin / skills-CLI layout, or a personal ~/.claude/skills copy)."""
    for d in (os.path.join(HERE, "..", "..", "brag-stems", "scripts"),
              os.path.expanduser("~/.claude/skills/brag-stems/scripts"),
              os.path.expanduser("~/.agents/skills/brag-stems/scripts")):
        if os.path.exists(os.path.join(d, "export_stems.py")):
            return os.path.abspath(d)
    raise SystemExit("brag-stems is not installed next to brag-stems-pro; install both skills.")


class Comp:
    """A brag composition: read/patch the root and the <audio> clips of composition/index.html."""

    def __init__(self, output_dir):
        self.od = os.path.abspath(output_dir)
        self.dir = os.path.join(self.od, "composition")
        self.path = os.path.join(self.dir, "index.html")
        self.src = open(self.path).read()
        root = re.search(r'id="root"[^>]*>', self.src).group(0)
        self.total = float(re.search(r'data-duration="([\d.]+)"', root).group(1))
        self.fps = int(float((re.search(r'data-fps="([\d.]+)"', root) or [0, 30])[1]))

    def audio(self):
        out = []
        for m in re.finditer(r"<audio\b([^>]*)>", self.src):
            a = m.group(1)
            g = lambda k: (re.search(k + r'="([^"]*)"', a) or [None, None])[1]
            auto = re.search(r"data-automation='([^']*)'", a)
            out.append({"tag": m.group(0), "id": g("id") or "", "src": g("src") or "",
                        "start": float(g("data-start") or 0), "dur": float(g("data-duration") or self.total),
                        "vol": float(g("data-volume") or 1), "track": g("data-track-index"),
                        "auto": json.loads(html.unescape(auto.group(1))) if auto else None})
        return out

    def stem_of(self, c):
        p = c["src"].lower()
        if "/vo/" in p or c["id"].startswith("vo"):
            return "dialogue"
        if "/sfx/" in p or c["id"].startswith("sfx"):
            return "sfx"
        return "music"

    def set_attrs(self, clip_id, **attrs):
        """attrs like data_start=1.2 → data-start="1.2"; automation=dict → data-automation='…'."""
        m = re.search(r'<audio\b[^>]*\bid="' + re.escape(clip_id) + r'"[^>]*>', self.src)
        tag = m.group(0)
        new = tag
        for k, v in attrs.items():
            if k == "automation":
                val = "'" + json.dumps(v, separators=(",", ":")) + "'"
                if "data-automation=" in new:
                    new = re.sub(r"data-automation='[^']*'", "data-automation=" + val, new)
                else:
                    new = new[:-1] + " data-automation=" + val + ">"
                continue
            name = k.replace("_", "-")
            val = f'{v:.3f}'.rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
            if re.search(r'\b' + name + r'="', new):
                new = re.sub(r'\b' + name + r'="[^"]*"', f'{name}="{val}"', new)
            else:
                new = new[:-1] + f' {name}="{val}">'
        self.src = self.src.replace(tag, new, 1)

    def save(self):
        open(self.path, "w").write(self.src)


def duck_lane(vo_spans, total, base, duck, pre=0.15, post=0.25, fade=0.9):
    """Volume points: `base` between lines, `duck` under each (start, end) narration span, fade out at the end."""
    pts = [{"t": 0, "v": duck if vo_spans and vo_spans[0][0] < pre else base}]
    for s, e in sorted(vo_spans):
        a, b = max(s - pre, 0.0), min(e + post, total)
        if a > pts[-1]["t"]:
            pts.append({"t": round(a, 3), "v": pts[-1]["v"]})
        pts.append({"t": round(max(a + 0.12, pts[-1]["t"]), 3), "v": duck})
        pts.append({"t": round(b, 3), "v": duck})
        pts.append({"t": round(min(b + 0.2, total), 3), "v": base})
    end = max(total - fade, pts[-1]["t"])
    pts.append({"t": round(end, 3), "v": pts[-1]["v"]})
    pts.append({"t": total, "v": 0})
    clean = []
    for p in pts:  # keep time strictly increasing
        if clean and p["t"] <= clean[-1]["t"]:
            clean[-1] = p
        else:
            clean.append(p)
    return {"version": 1, "lanes": [{"target": "volume", "points": clean}]}


def lane_levels(auto):
    """(base, duck) volume levels from an existing automation lane."""
    vals = [p["v"] for p in auto["lanes"][0]["points"] if p["v"] > 0]
    return (max(vals), min(vals)) if vals else (0.3, 0.12)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def lufs(path, start=None, length=None):
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start), "-t", str(length)]
    cmd += ["-i", path, "-af", "ebur128", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True).stderr
    i = re.findall(r"^\s+I:\s+(-?[\d.]+|-inf) LUFS", r, re.M)
    return float(i[-1]) if i and i[-1] != "-inf" else -70.0


def speech_regions(path, noise="-40dB", min_sil=0.25):
    """[(start, end)] of non-silent audio."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                        f"silencedetect=noise={noise}:d={min_sil}", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    dur = duration(path)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    sil = list(zip(starts, ends + [dur] * (len(starts) - len(ends))))
    spans, cur = [], 0.0
    for s, e in sil:
        if s > cur + 0.05:
            spans.append((max(cur, 0.0), s))
        cur = e
    if dur > cur + 0.05:
        spans.append((cur, dur))
    return spans


def group_regions(spans, n):
    """Merge speech regions into exactly n groups by cutting at the n-1 widest gaps."""
    if len(spans) < n:
        return None
    gaps = sorted(range(len(spans) - 1), key=lambda i: spans[i + 1][0] - spans[i][1], reverse=True)[:n - 1]
    out, cur = [], spans[0]
    for i in range(len(spans) - 1):
        if i in gaps:
            out.append(cur)
            cur = spans[i + 1]
        else:
            cur = (cur[0], spans[i + 1][1])
    return out + [cur]


def beats(audio_path, workdir):
    """[(time, strength)] via `hyperframes beats` on a throwaway one-clip project (no Python deps)."""
    proj = os.path.join(workdir, "_beats")
    os.makedirs(os.path.join(proj, "assets"), exist_ok=True)
    ext = os.path.splitext(audio_path)[1]
    link = os.path.join(proj, "assets", "track" + ext)
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(os.path.abspath(audio_path), link)
    d = duration(audio_path)
    open(os.path.join(proj, "index.html"), "w").write(
        f'<!doctype html><html><body><div id="root" data-composition-id="main" data-start="0" data-width="1080" '
        f'data-height="1920" data-duration="{d:.2f}" data-fps="30"><audio id="bg-music" src="assets/track{ext}" '
        f'data-start="0" data-duration="{d:.2f}" data-track-index="1" data-volume="1"></audio></div></body></html>')
    r = subprocess.run(HF + ["beats", proj, "--json"], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("hyperframes beats failed:\n" + (r.stdout + r.stderr)[-1500:])
    data = json.load(open(os.path.join(proj, "beats", "assets", "track" + ext + ".json")))
    return [(b["time"], b["strength"]) for b in data["beats"]]


def bass_js(audio_path, out_js, fps, total):
    """Per-frame low-end energy (0..1) as window.HF_BASS, for compositions with an audio-reactive glow."""
    n = int(round(48000 / fps))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", audio_path, "-t", str(total), "-af",
                        f"aresample=48000,pan=mono|c0=0.5*c0+0.5*c1,lowpass=f=180,asetnsamples=n={n}:p=0,"
                        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    db = [float(x) if x != "-inf" else -90.0 for x in re.findall(r"RMS_level=(-?[\d.]+|-inf)", r)]
    if not db:
        return
    lo, hi = -50.0, max(db)
    vals = [round(min(max((d - lo) / max(hi - lo, 1e-6), 0.0), 1.0), 2) for d in db]
    open(out_js, "w").write("window.HF_BASS=" + json.dumps(vals) + ";\n")


def volume_expr(points, offset=0.0):
    """FFmpeg volume expression (eval=frame) for a piecewise-linear automation lane; t is clip-local."""
    pts = [(p["t"] - offset, p["v"]) for p in points]
    expr = str(pts[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(pts, pts[1:]))):
        expr = f"if(between(t,{t0},{t1}),({v0}+({v1}-{v0})*(t-{t0})/{max(t1 - t0, 1e-6)}),{expr})"
    return f"if(lt(t,{pts[0][0]}),{pts[0][1]},{expr})"


def peak_db(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "astats=metadata=0", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    p = re.findall(r"Overall\n(?:.*\n)*?.*Peak level dB: (-?[\d.]+|-inf)", r)
    q = re.findall(r"Peak level dB: (-?[\d.]+|-inf)", r)
    v = (p or q or ["-inf"])[-1]
    return -90.0 if v == "-inf" else float(v)
