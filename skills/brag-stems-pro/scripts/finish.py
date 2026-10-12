"""Re-render after a voice or music swap and rebuild every deliverable.

usage: python3 finish.py <output_dir> [--skip-render] [--no-prompters]

1. hyperframes check + render  → brag.mp4 (the previous one is kept as brag.before-swap.mp4)
2. bake brag.jpg as frame 0 (if a poster exists)
3. social loudness              (brag-stems normalize_video.py)
4. stems + two-track mix        (brag-stems export_stems.py)
5. transcript + teleprompters   (brag-stems teleprompter.py, then record_prompter.py)
"""
import argparse, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pro_common import HF, HERE, stems_scripts  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("output_dir")
ap.add_argument("--skip-render", action="store_true")
ap.add_argument("--no-prompters", action="store_true")
a = ap.parse_args()
od = os.path.abspath(a.output_dir)
comp = os.path.join(od, "composition")
SS = stems_scripts()
video = os.path.join(od, "brag.mp4")


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"failed: {' '.join(cmd[:4])}…\n" + (r.stdout + r.stderr)[-3000:])
    return r.stdout


if not a.skip_render:
    run(HF + ["check"], cwd=comp)
    raw = os.path.join(od, "brag.raw.mp4")
    run(HF + ["render", "--quality", "high", "-o", raw], cwd=comp)
    if os.path.exists(video):
        shutil.copy(video, os.path.join(od, "brag.before-swap.mp4"))
    poster = os.path.join(od, "brag.jpg")
    if os.path.exists(poster):
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-i", poster, "-filter_complex",
             "[1:v][0:v]scale2ref[p][v];[v][p]overlay=enable='eq(n,0)'[o]", "-map", "[o]", "-map", "0:a?",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy",
             "-movflags", "+faststart", video])
        os.remove(raw)
    else:
        os.replace(raw, video)
    print("rendered brag.mp4" + (" (poster baked as frame 0)" if os.path.exists(poster) else ""))

print(run([sys.executable, os.path.join(SS, "normalize_video.py"), video]).strip())
print(run([sys.executable, os.path.join(SS, "export_stems.py"), od]).strip().splitlines()[-1])
if os.path.exists(os.path.join(comp, "assets", "vo", "script.json")) and not a.no_prompters:
    print(run([sys.executable, os.path.join(SS, "teleprompter.py"), od, "--render"]).strip())
    print(run([sys.executable, os.path.join(HERE, "record_prompter.py"), od, "--render"]).strip())
print("done: brag.mp4, stems/ (stems, mix, transcript, teleprompters) are current")
