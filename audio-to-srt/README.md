# Audio → SRT (Windows)

OpenWhisperer’s upstream repo is a **macOS** voice app (Swift / Apple Silicon). It cannot convert audio files to SRT on Windows.

This folder adds a local **faster-whisper** pipeline that does audio/video → `.srt` (+ `.txt`) on your PC (RTX GPU when available).

## Quick start

1. Put an audio/video file in `input/` (or pass a path).
2. Double-click `transcribe.bat`, **or** run:

```powershell
cd "D:\Github Projects\Openwhispered\audio-to-srt"
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\Recording (4).m4a" --model medium --txt
```

Output goes to `output\<name>.srt` (and `.txt` with `--txt`).

While it runs you’ll see a live line like:

```text
[##############--------------]  52.3% done |  47.7% left (3:41 / 7:02)
```

`--speakers` **reuses** an existing `output\<name>.srt` (and caches) so Whisper is not re-run.
Diarization turns are cached to `output\<name>.diarization.json` after the first success.

## Speakers (name people in the SRT)

Use `--speakers` to:

1. Detect how many distinct voices are in the file
2. Show sample transcript lines for each voice every N seconds (`--sample-interval`, default 120)
3. Ask you to type a name for each voice
4. Write that name on **every** line for that voice in the SRT / TXT

Example cue:

```text
12
00:03:41,200 --> 00:03:44,800
Alex: Thanks for joining today.
```

### One-time setup

```powershell
cd "D:\Github Projects\Openwhispered\audio-to-srt"
.\.venv\Scripts\pip.exe install -r requirements-speakers.txt
```

Then:

1. Create a free [Hugging Face](https://huggingface.co/) account
2. Accept the terms for this model (same HF account as your token):
   - https://huggingface.co/pyannote/speaker-diarization-community-1
3. Create a token at https://huggingface.co/settings/tokens and put it in the repo `.env`:

```text
HF_TOKEN=hf_your_token_here
```

(Or `setx HF_TOKEN "hf_..."` — open a new terminal after `setx`.)

### Run with speakers

```powershell
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\Test.m4a" --model medium --txt --speakers
```

Optional:

```text
--sample-interval 90     show sample lines ~every 90s for each speaker
--play-samples           play a short clip (needs ffplay) when asking for a name
--names "Systemair,UWO"  skip typing (order = detected speaker order)
--names "SPEAKER_00=Systemair,SPEAKER_01=UWO"
--hf-token hf_...        token for this run only
```

Interactive session looks like:

```text
Detected 2 speaker(s).
============================================================
Speaker 1/2  [SPEAKER_00]  ~12:40 of speech
Sample lines every ~120s:
  [0:14] Welcome everyone to the call...
  [2:21] From our side we can share the specs...
  Name for this speaker (Enter to keep SPEAKER_00): Systemair
```

## Options

```text
--model tiny|base|small|medium|large-v3   (default: medium)
--language en                             (omit to auto-detect)
--device cuda|cpu|auto                    (default: auto)
--speakers                                detect + name speakers
--sample-interval SECONDS                 (default: 120)
--play-samples
--names "A,B" | "SPEAKER_00=A,SPEAKER_01=B"
```

Larger models = better accuracy, slower first download. Speaker detection is separate from Whisper and needs the Hugging Face setup above.
