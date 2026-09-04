<p align="center">
  <img src="icon.png" width="96" alt="Open Whisperer icon">
</p>

# OpenWhisper

Voice for coding agents on **Apple Silicon Macs**, plus a **Windows audio → SRT** toolkit added in this fork.

This repo is based on [PerIPan/OpenWhisperer](https://github.com/PerIPan/OpenWhisperer). Upstream is a macOS menubar app. Here we also ship `audio-to-srt/` so you can transcribe long recordings to subtitles on a Windows PC (with optional speaker names).

---

## What’s in this repo

| Piece | Platform | What it does |
|-------|----------|--------------|
| **OpenWhisperer app** (`app/`) | macOS 14+, Apple Silicon | Dictate into Claude Code / Codex / Pi / Antigravity; hear spoken replies. All local (WhisperKit + Kokoro/Supertonic). |
| **Audio → SRT** (`audio-to-srt/`) | Windows | Turn audio/video into `.srt` / `.txt` with faster-whisper. Optional speaker detection + interactive naming. |

Models are **not** in Git. They download on first use (Hugging Face / Whisper caches). Do not commit `.env`, media, `ffmpeg.exe`, or `.venv`.

---

## Changes in this fork (Lithiumwow)

Windows-focused work that is **not** part of the original Mac app:

- **`audio-to-srt/`** — local transcription pipeline for Windows (CUDA when available).
- **Live progress** — `% done` / `% left` and time while Whisper runs.
- **`--speakers`** — pyannote diarization, sample lines every N seconds, you name each voice once, names applied across the whole SRT.
- **Caches** — reuses existing SRT / `.cues.json` / `.diarization.json` so you don’t re-run Whisper or diarization every time.
- **Windows torchcodec workaround** — feeds audio in-memory so pyannote doesn’t need broken FFmpeg DLLs.
- **`.env` + `.env.example`** — `HF_TOKEN` for gated pyannote models (token never committed).

Mac app behavior is still upstream OpenWhisperer (native Swift STT/TTS, menubar, hooks). See [AGENTS.md](AGENTS.md) for architecture.

---

## Windows: Audio → SRT

Details and flags: **[audio-to-srt/README.md](audio-to-srt/README.md)**.

### Setup (once)

1. Put `ffmpeg.exe` next to `audio-to-srt/transcribe_to_srt.py` (or on `PATH`).
2. Create a venv and install Whisper:

```powershell
cd audio-to-srt
python -m venv .venv
.\.venv\Scripts\pip.exe install faster-whisper
```

3. For speaker names, also install diarization deps and accept the model terms:

```powershell
.\.venv\Scripts\pip.exe install -r requirements-speakers.txt
```

- Accept: https://huggingface.co/pyannote/speaker-diarization-community-1  
- Token: https://huggingface.co/settings/tokens  
- Put `HF_TOKEN=hf_...` in a repo-root `.env` (see `.env.example`).

### Transcribe

```powershell
cd audio-to-srt
# drop a file in input\, or pass a path:
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\meeting.m4a" --model medium --txt
```

Or double-click `transcribe.bat`.

Progress looks like:

```text
[##############--------------]  52.3% done |  47.7% left (3:41 / 7:02)
```

Output: `output\<name>.srt` (and `.txt` with `--txt`).

### Name speakers

```powershell
.\.venv\Scripts\python.exe transcribe_to_srt.py "input\meeting.m4a" --model medium --txt --speakers
```

Flow:

1. Detects how many speakers are in the file.
2. Shows sample lines per speaker (default every ~120s; `--sample-interval`).
3. You type a name (e.g. `Systemair`, `UWO`).
4. Rewrites the SRT with `Name: …` on every matching line.

Useful flags:

| Flag | Meaning |
|------|---------|
| `--speakers` | Diarize + interactive naming (reuses SRT/caches when present) |
| `--names "A,B"` | Skip prompts (order = detected speaker order) |
| `--force-transcribe` | Re-run Whisper even if a cache/SRT exists |
| `--force-diarize` | Re-run diarization even if `.diarization.json` exists |
| `--play-samples` | Play a short clip when naming (needs `ffplay`) |

---

## Mac: OpenWhisperer app

**Requires:** Apple Silicon Mac, macOS 14+.

### Install (prebuilt)

Upstream release DMG:

[OpenWhisperer-2.0.4.dmg](https://github.com/PerIPan/OpenWhisperer/releases/download/v2.0.4/OpenWhisperer-2.0.4.dmg)

Drag to Applications. If Gatekeeper blocks an unsigned/dev build:

```bash
xattr -cr /Applications/OpenWhisperer.app
```

On first launch the app downloads Whisper + Kokoro models and starts a loopback TTS server on port `8000`.

### Build from this repo

```bash
git clone https://github.com/Lithiumwow/OpenWhisper.git
cd OpenWhisper/app
chmod +x build-dmg.sh
./build-dmg.sh
```

Then use **Settings → Agents → Connect** for Claude Code, Codex, Pi, or Antigravity.

### What the Mac app does (short)

- **Dictation** — Hold-to-Talk / Press-to-Talk / Hands-Free; text typed into the focused app (clipboard never used).
- **Spoken replies** — after voice turns, the agent calls an in-app `speak` tool; Kokoro or Supertonic-3 plays locally.
- **Settings** — Dictation, Voice (100+ voices / many languages), Agents, Advanced, General (themes, permissions).

Full upstream changelog and behavior notes live in older releases of [PerIPan/OpenWhisperer](https://github.com/PerIPan/OpenWhisperer). Day-to-day contributor rules: [AGENTS.md](AGENTS.md).

---

## Repo layout

```text
OpenWhisper/
├── README.md                 # this file
├── AGENTS.md                 # architecture + commands for contributors
├── audio-to-srt/             # Windows: Whisper → SRT (+ optional speakers)
│   ├── transcribe_to_srt.py
│   ├── transcribe.bat
│   ├── requirements-speakers.txt
│   ├── input/                # put audio here (gitignored contents)
│   └── output/               # SRT/TXT/caches (gitignored contents)
├── app/                      # macOS Swift menubar app
├── hooks/                    # Claude / Codex / Antigravity voice hooks
├── pi/                       # Pi extension
└── scripts/speak.sh          # pipe text → local TTS (Mac, app running)
```

---

## Troubleshooting

**Windows — transcription**

- `ffmpeg not found` → place `ffmpeg.exe` in `audio-to-srt/` or on `PATH`.
- Slow / CPU only → install a CUDA build of the stack if you have an NVIDIA GPU; otherwise `--device cpu` uses int8.

**Windows — `--speakers`**

- `403` / gated repo → accept [speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) with the same account as `HF_TOKEN`.
- torchcodec / libtorchcodec errors → use this repo’s script (in-memory waveform). Don’t pass a bare file path into pyannote on Windows.

**Mac — no spoken reply**

- Only **dictated** turns speak by default (typed prompts stay silent).
- `curl http://localhost:8000/v1/models` — TTS server must be up (app running).

**Mac — dictation doesn’t type**

- Grant Accessibility + Microphone; after a rebuild, remove and re-add the app under Accessibility.

---

## Credits

- Upstream app: [PerIPan/OpenWhisperer](https://github.com/PerIPan/OpenWhisperer) — WhisperKit, FluidAudio / Kokoro / Supertonic-3
- Windows STT: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Speakers: [pyannote.audio](https://github.com/pyannote/pyannote-audio) ([community-1](https://huggingface.co/pyannote/speaker-diarization-community-1))

## License

MIT
