---
name: brag-stems-pro
description: Everything in /brag-stems, plus a real-voice and own-music workflow. It makes a recording teleprompter (pre-roll countdown, per-line cues, music-bed guide) for voice talent, imports their take back onto the exact line timings, and writes a Suno prompt and timing sheet for custom music. It then fits returned tracks so the strongest beat lands on the logo hit, previews each on the real video, and re-renders with the chosen one. Use for "/brag-stems-pro", recording a human voiceover for a brag video, or swapping in Suno or other custom music.
---

# /brag-stems-pro

`/brag-stems-pro` = `/brag-stems` + two round trips:

- **Real voice:** a recording teleprompter → talent records → `import_voice.py` puts every line on its exact original frame → `finish.py`.
- **Own music:** `suno_prompt.py` writes the prompt and timing sheet → the user generates in Suno → `fit_music.py` lines up and previews every version → accept one → `finish.py`.

It needs the `brag` and `brag-stems` skills installed alongside it. The scripts find `brag-stems/scripts` as a sibling folder or in `~/.claude/skills`. All scripts are standard-library Python 3.9+ plus ffmpeg and the Hyperframes CLI (pinned to `0.8.143`; override with `HYPERFRAMES_PKG`).

## Dispatch

- **New video:** run `brag-stems` with the same arguments (it runs `/brag`, social loudness, stems and transcript). Then do Step P1, and offer P2–P3.
- **`--only <output-dir>`:** start from an existing brag output folder. If `stems/transcript.json` is missing, run brag-stems' Steps 5–6 first.
- **`--voice-in <output-dir> [take]`:** jump to Step P2.
- **`--music <output-dir>`:** jump to Step P3.

## Step P1: Recording teleprompter

```bash
python3 <skill-dir>/scripts/record_prompter.py <output-dir> --render              # stems/teleprompter-record.mp4
python3 <skill-dir>/scripts/record_prompter.py <output-dir> --rehearsal --render  # optional practice version
```

**Record version** (1920×1080, video length plus a 5s pre-roll):

- a big 5-4-3-2-1 countdown with three beeps on 3-2-1; program time 00:00:00:00 is the silent beat after the third beep;
- a running program timecode, negative during the pre-roll;
- a status line: "LINE 3 IN 1.2s", then "READ · LINE 3 / 7";
- a yellow cue bar that fills over the 1.5s before each line, an arrow that turns yellow on the cue, and words that light up at pace;
- guide audio of the **music + sfx bed only**, so no synthetic voice bleeds into the mic.

**Rehearsal version:** the same, with the original narration at −12 dB.

It also writes `stems/recording-guide.txt`, step-by-step instructions for the talent or engineer with every line's in/out timecode. Point the user at it.

## Step P2: Import the real voice

The talent records in one continuous take, leaving clear pauses between lines. Pickups can be separate files named after the line (`vo3.wav`, `vo3-take2.wav`); the newest file per line wins. Everything goes in `<output-dir>/voice-takes/`.

```bash
python3 <skill-dir>/scripts/import_voice.py <output-dir> --talent "Name" --dry-run   # check the split first
python3 <skill-dir>/scripts/import_voice.py <output-dir> --talent "Name"
python3 <skill-dir>/scripts/finish.py <output-dir>
```

**How the take is placed:**

- The take is split at its N−1 widest pauses into the N script lines.
- Each line's speech onset is placed on the exact frame of the original line. The original timings are saved once in `composition/assets/vo-synthetic/slots.json`, so re-imports and pickups never drift.
- A read that's too long for its slot is sped up to at most 1.12× with pitch preserved (`--max-stretch`). Anything longer is left long and flagged, and moved to an alternate track.
- One gain is applied to the whole take to match the original narration level. There's no compression and no line-by-line leveling.
- The music ducking is rebuilt around the new reads.
- The synthetic voice files are backed up to `composition/assets/vo-synthetic/`, and `script.json` records the talent.

Always show the dry-run report before writing. If the talent changed wording, update `composition/assets/vo/script.json` before `finish.py`, so the transcript and teleprompters match the real read.

## Step P3: Suno music, round trip

1. Write the prompt. Build the `--style` from the brag plan's tone (genre, instruments, mood), using no artist names:

   ```bash
   python3 <skill-dir>/scripts/suno_prompt.py <output-dir> --style "late-night soul-hop, warm Rhodes, dusty drums, deep bass"
   ```

   This writes `suno/suno-prompt.md`: the Style of Music, Exclude Styles, Instrumental on, title, optional structure tags, and a timing sheet with the scene cuts, the **main hit** (default: the start of the last scene, the logo), the narration windows and the target tempo. Show the user the style line and the hit time.

2. **The user generates in Suno with their own account and credits.** Each Create makes 2 versions, so 1–2 Creates give 2–4 options. Don't drive suno.com or use unofficial Suno APIs. Remind the user that free-plan Suno songs are for non-commercial use only; ads need a paid plan.

3. The user drops the downloads into `suno/incoming/`. Then fit and preview them:

   ```bash
   python3 <skill-dir>/scripts/fit_music.py <output-dir>
   ```

   For each track it:
   - detects the beats;
   - picks the offset that lands its strongest downbeat on the main hit, preferring a busy, non-silent window;
   - trims it to the video length with a 0.9s fade-out;
   - matches the original music level, without pushing peaks into clipping;
   - mixes it under the narration with the same ducking, onto the real picture.

   The results are `suno/previews/option-N.mp4` and `suno/previews/options.md`. Send the previews to the user.

4. When the user picks one:

   ```bash
   python3 <skill-dir>/scripts/fit_music.py <output-dir> --accept N
   python3 <skill-dir>/scripts/finish.py <output-dir>
   ```

   If they reject all of them, they press Create again in Suno (and can tweak the style line), drop in the new files, and you re-run `fit_music.py`; options are numbered by file name.

## finish.py

It re-renders the composition. The previous video is kept as `brag.before-swap.mp4`. Then it:

1. bakes `brag.jpg` as frame 0;
2. applies social loudness;
3. re-exports the stems and two-track mix;
4. re-renders the transcript, the teleprompter and the recording teleprompter.

`--skip-render` redoes only the audio deliverables, from the current `brag.mp4`.

**Gate:**
- `brag.mp4`, every stem and both teleprompters have the right lengths (the record version is the video length plus the pre-roll);
- after a voice import, the line in-points in `stems/transcript.txt` match `vo-synthetic/slots.json` to the frame.

## Delivery

Report the files that changed (the video, `stems/`, `suno/previews/` and the recording guide). Always flag:

- reads that were sped up, or that run long;
- any music option that couldn't place the hit (track too short);
- the Suno licensing note, when music went into an ad.
