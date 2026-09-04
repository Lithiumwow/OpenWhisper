# Audio → SRT (Windows)

Transcribe audio/video to `.srt` (+ optional `.txt`) with **faster-whisper**.  
Optional **`--speakers`**: detect voices, name them interactively, rewrite the SRT.

The parent OpenWhisperer app is **macOS-only**. This folder is the Windows path.

## Quick start

1. Place `ffmpeg.exe` in this folder (or on `PATH`).
2. Put a file in `input/`, or pass a path.
3. Run:

```powershell
cd audio-to-srt
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\meeting.m4a" --model medium --txt
```

Or double-click `transcribe.bat`.

Output: `output\<name>.srt` (and `.txt` with `--txt`).

Progress:

```text
[##############--------------]  52.3% done |  47.7% left (3:41 / 7:02)
```

## Speakers

```powershell
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\meeting.m4a" --model medium --txt --speakers
```

1. Detects distinct speakers (pyannote).
2. Shows sample lines every `--sample-interval` seconds (default 120).
3. You enter a name per speaker.
4. Writes `Name: text` on every matching cue.

`--speakers` **reuses** an existing SRT / `.cues.json` / `.diarization.json` when present (skips Whisper and/or diarization). Use `--force-transcribe` / `--force-diarize` to redo those steps.

### One-time speaker setup

```powershell
.\.venv\Scripts\pip.exe install -r requirements-speakers.txt
```

1. Accept https://huggingface.co/pyannote/speaker-diarization-community-1  
2. Create a token at https://huggingface.co/settings/tokens  
3. Repo-root `.env`:

```text
HF_TOKEN=hf_your_token_here
```

### Optional flags

```text
--sample-interval 90
--play-samples
--names "Alice,Bob"
--names "SPEAKER_00=Alice,SPEAKER_01=Bob"
--hf-token hf_...
--force-transcribe
--force-diarize
```

## Options

```text
--model tiny|base|small|medium|large-v3   (default: medium)
--language en                             (omit = auto-detect)
--device cuda|cpu|auto                    (default: auto)
--speakers
--txt
```

Larger models = better accuracy, slower first download.
