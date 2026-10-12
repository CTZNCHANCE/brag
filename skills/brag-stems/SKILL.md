---
name: brag-stems
description: Run /brag, then hand off a post-production kit with the video. The kit holds the audio as separate stems (dialogue, music, sfx), the baked two-track mix, a timecoded narration transcript (txt/srt/vtt/json) and a teleprompter video for voice talent. Use when someone says "/brag-stems", wants a brag video "with stems", or wants stems, a transcript or a teleprompter for an existing brag output folder.
---

# /brag-stems

`/brag-stems` = `/brag`, plus a post-production kit, every time:

- **Stems:** `dialogue.wav`, `music.wav` and `sfx.wav`. Clean and unprocessed (no limiter, compression or normalization), 48 kHz / 24-bit stereo, full length, all starting at 0:00.
- **Two-track mix:** `mix.wav`, exactly as baked into `brag.mp4`.
- **Transcript:** `transcript.txt` (timecoded, HH:MM:SS:FF), `.srt`, `.vtt` and `.json` (line, sentence and word timings).
- **Teleprompter:** `teleprompter.mp4` (1920×1080). It shows a running timecode, a reading guide, the script scrolling with each line's in-point, word-by-word highlighting and a progress bar. The original narration plays as a guide track.

Everything lands in `<output-dir>/stems/`. Use it to remix in a DAW, re-record the narration with a real voice, caption the video, or recut it in an editor.

## House defaults (this fork)

These apply to every run unless the user says otherwise:

- **Pinned Hyperframes:** use `npx hyperframes@0.8.143` for every Hyperframes command in the run (`check`, `snapshot`, `render`, `tts`), including brag's own steps. `teleprompter.py` uses the same pin; override it with `HYPERFRAMES_PKG=hyperframes@<version>`.
- **Social loudness:** after the poster is baked, raise `brag.mp4` to about −14 LUFS with Step 4.5. Only the posted video is normalized; the stems stay clean.
- **Length:** brag's 15–25s window is a default, not a cap. When the user asks for 30–45s, pass `--duration` and pace scenes to it.
- **Stems every time:** even when plain `/brag` was invoked, finish with Steps 4.5–6.
- **Sharing:** upload to Google Drive (or anywhere else) only when the user asks. With Drive for Desktop, copy files into the synced folder, then read the link id from the `com.google.drivefs.item-id#S` extended attribute.

### Setup notes

- **Kokoro voice (`--voice`):** `kokoro-onnx` needs Python 3.10+. If the system Python is older, make a venv (`uv venv --python 3.12 ~/.venvs/hyperframes-tts && uv pip install --python ~/.venvs/hyperframes-tts/bin/python kokoro-onnx soundfile`). Then prefix the Hyperframes commands with `HYPERFRAMES_PYTHON=~/.venvs/hyperframes-tts/bin/python`.
- **`npx` in loops:** inside a `while read` loop, end each `npx` call with `</dev/null`, or it swallows the loop's input and only the first line runs.
- **Speech recognition:** skip `hyperframes transcribe` for the transcript. On short TTS clips it installs slowly and returns garbage; Step 6 times lines from the audio itself.
- **Synthetic voices** are for promo narration. If a product's own host or character voices must be real, licensed people, keep the two separate, and swap a human read in via `script.json` and Step 6.

## Dispatch

- **`/brag-stems --only <output-dir>`**: skip making the video and run the steps below on an existing brag output folder. It needs `composition/index.html`; `brag.mp4` is optional.
- **Anything else**: pass every argument through unchanged to the `brag` skill (`--full`, `--voice`, `--format vertical`, `--duration`, …). Follow its workflow to its final gate (`brag.mp4`, poster, share copy), then continue here.

## Composition conventions (tell Hyperframes during brag Step 3)

Stem sorting reads each `<audio>` element's `src` folder first, and its `id` prefix second:

| Stem | Asset folder | id prefix |
|---|---|---|
| dialogue | `assets/vo/` | `vo` |
| sfx | `assets/sfx/` | `sfx` |
| music | `assets/music/` (and anything else) | — |

- Every `<audio>` needs an explicit `data-start` and `data-duration`.
- Music ducking belongs in `data-automation` volume lanes. The music stem reproduces it, so it matches the mix.
- With `--voice`, save the exact text sent to TTS, keyed by each dialogue `<audio>` id:

```json
// composition/assets/vo/script.json
{"voice": "Kokoro af_heart", "lines": {"vo1": "First narration line.", "vo2": "Second line."}}
```

## Step 4.5: Social loudness

```bash
python3 <skill-dir>/scripts/normalize_video.py <output-dir>/brag.mp4
```

It raises `brag.mp4` toward −14 LUFS (FFmpeg `loudnorm`, true-peak ceiling −1.5 dB), stream-copies the video so the baked poster frame survives, and keeps the original as `brag.prenorm.mp4`.

- Mixes with big SFX hits can land a little under −14 rather than being squashed. That's expected.
- On macOS it encodes with Apple's AAC encoder; FFmpeg's built-in one can add a peak at the start of the file on loud mixes.

Run it before Step 5, so `mix.wav` matches the posted video.

## Step 5: Stems + two-track mix

```bash
python3 <skill-dir>/scripts/export_stems.py <output-dir>
```

It writes the stems, `mix.wav` and a `README.txt` listing every clip's start time, length and volume plus each file's loudness.

The stems are deliberately left unprocessed. If the final video was loudness-normalized or limited, the stems summed will be quieter than `mix.wav`. Say so in one line and suggest a master limiter.

**Gate:** the four WAVs exist, and their durations equal the composition duration (check with `ffprobe`).

## Step 6: Transcript + teleprompter (when there is narration)

```bash
python3 <skill-dir>/scripts/teleprompter.py <output-dir> --render
```

It needs `composition/assets/vo/script.json` and uses `stems/dialogue.wav` as the guide audio, so run Step 5 first.

**How the timing works:**

- Line in/out times come from the actual speech inside each clip, so they're exact to the frame.
- Sentence breaks come from the pauses in the audio.
- Word timing within a sentence is estimated from word length.
- No speech recognition is involved, so brand names are always spelled right.

The teleprompter's source is a Hyperframes composition in `<output-dir>/teleprompter/`; edit it and re-render with `npx hyperframes@0.8.143 render`. For a beam-splitter rig, mirror the output:

```bash
ffmpeg -i stems/teleprompter.mp4 -vf hflip -c:a copy stems/teleprompter-mirrored.mp4
```

**Gate:** `teleprompter.mp4` is the same length as the video. Spot-check one frame mid-line (`ffmpeg -ss <t> -i stems/teleprompter.mp4 -frames:v 1 check.jpg`).

## Delivery

Report the `stems/` folder (stems, mix, transcript, teleprompter) alongside `brag.mp4`, `brag.jpg` and `share-copy.txt`.

If the narration will be re-recorded by a person, remind the user to update `script.json` to the final read and re-run Step 6.

## Requirements

Everything `/brag` needs (Node 22+, FFmpeg on `PATH`, the Hyperframes CLI), plus Python 3.9+. No extra Python packages.
