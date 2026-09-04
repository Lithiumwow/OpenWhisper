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

## Live Teams / speaker capture

Record **what plays through your speakers/headphones** (WASAPI loopback), then
transcribe to SRT when you stop. Good for Teams calls: you hear remote audio;
this captures that mix (not your microphone).

### Setup (once)

```powershell
.\.venv\Scripts\pip.exe install -r requirements-live.txt
```

### Record a call

1. Start the script **before or during** the call.
2. Make sure Teams audio is going to the device you capture (default speaker, or pick one).
3. Press **Ctrl+C** when the call ends — it saves a WAV and runs Whisper → SRT.

```powershell
# list devices (use a name substring with --loopback)
.\.venv\Scripts\python.exe record_call.py --list-devices

# default speaker loopback → output\call-YYYYMMDD-HHMMSS.wav → SRT
.\.venv\Scripts\python.exe record_call.py --model medium --txt

# e.g. SteelSeries "Chat" or headphones
.\.venv\Scripts\python.exe record_call.py --loopback Chat --model medium --txt

# after recording, also run speaker naming
.\.venv\Scripts\python.exe record_call.py --loopback Headphones --speakers --txt
```

Or double-click `record_call.bat`.

Tips:

- If the level meter stays flat, Teams is using another output — `--list-devices` then `--loopback "…"`.
- Your own voice is only included if it is also played back on that output (usually it is not).
- `--no-transcribe` saves the WAV only.
