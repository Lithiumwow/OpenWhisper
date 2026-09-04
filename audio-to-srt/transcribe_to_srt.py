"""Transcribe audio/video to SRT with faster-whisper (optional speaker labels)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from faster_whisper import WhisperModel


def load_dotenv_files(*paths: Path) -> None:
    """Load KEY=VALUE lines from .env files into os.environ (no overwrite)."""
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Bare token line (user pasted hf_... alone)
            if "=" not in line and line.startswith("hf_"):
                os.environ.setdefault("HF_TOKEN", line)
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                os.environ.setdefault(key, val)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    speaker: str | None = None


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000.0))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def parse_timestamp(ts: str) -> float:
    # 00:01:02,345 or 00:01:02.345
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"bad timestamp: {ts}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def format_clock(seconds: float) -> str:
    """Human clock like 1:23:45 (no millis) for progress lines."""
    if seconds < 0:
        seconds = 0.0
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def print_progress(done_sec: float, total_sec: float, width: int = 28) -> None:
    """Overwrite one console line with % done / % left and a bar."""
    if total_sec <= 0:
        pct = 0.0
    else:
        pct = min(100.0, max(0.0, (done_sec / total_sec) * 100.0))
    left = 100.0 - pct
    filled = int(round(width * pct / 100.0))
    bar = "#" * filled + "-" * (width - filled)
    line = (
        f"\r[{bar}] {pct:5.1f}% done | {left:5.1f}% left "
        f"({format_clock(done_sec)} / {format_clock(total_sec)})"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


SPEAKER_PREFIX_RE = re.compile(r"^([^:]{1,40}):\s+(.*)$")


def write_srt(cues: list[Cue], out_path: Path) -> None:
    lines: list[str] = []
    n = 0
    for cue in cues:
        text = (cue.text or "").strip()
        if not text:
            continue
        if cue.speaker:
            text = f"{cue.speaker}: {text}"
        n += 1
        lines.append(str(n))
        lines.append(f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}")
        lines.append(text)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_txt(cues: list[Cue], out_path: Path) -> None:
    parts: list[str] = []
    for cue in cues:
        text = (cue.text or "").strip()
        if not text:
            continue
        if cue.speaker:
            parts.append(f"{cue.speaker}: {text}")
        else:
            parts.append(text)
    out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def read_srt(path: Path) -> list[Cue]:
    """Parse an existing SRT into cues (strips a leading 'Name: ' if present)."""
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    cues: list[Cue] = []
    for block in blocks:
        lines = [ln.strip("\ufeff") for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # Optional index line
        if "-->" not in lines[0] and len(lines) >= 3:
            timing = lines[1]
            body = " ".join(lines[2:])
        elif "-->" in lines[0]:
            timing = lines[0]
            body = " ".join(lines[1:])
        else:
            continue
        if "-->" not in timing:
            continue
        left, _, right = timing.partition("-->")
        start = parse_timestamp(left)
        end = parse_timestamp(right)
        speaker = None
        m = SPEAKER_PREFIX_RE.match(body)
        # Only treat as speaker label if it looks like SPEAKER_XX or a short name
        if m and (" " not in m.group(1) or m.group(1).startswith("SPEAKER")):
            # Prefer stripping only when already labeled by us / diarization
            if m.group(1).startswith("SPEAKER") or len(m.group(1)) <= 40:
                # Keep body as-is for unlabeled transcripts that happen to contain "Note: ..."
                # Heuristic: strip only SPEAKER_* or known short labels without lowercase sentence start
                if m.group(1).startswith("SPEAKER") or m.group(1)[:1].isupper():
                    # Too aggressive for "So, ..." — require colon style Name with no comma in name
                    if "," not in m.group(1) and not m.group(1).endswith("."):
                        # Still risky. Only strip SPEAKER_* from reused files.
                        if m.group(1).startswith("SPEAKER"):
                            speaker = m.group(1)
                            body = m.group(2)
        cues.append(Cue(start=start, end=end, text=body.strip(), speaker=speaker))
    return cues


def save_cues_cache(path: Path, cues: list[Cue]) -> None:
    payload = [asdict(c) for c in cues]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")


def load_cues_cache(path: Path) -> list[Cue]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Cue(**row) for row in data]


def save_turns_cache(path: Path, turns: list[tuple[float, float, str]]) -> None:
    payload = [{"start": a, "end": b, "speaker": s} for a, b, s in turns]
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_turns_cache(path: Path) -> list[tuple[float, float, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(float(r["start"]), float(r["end"]), str(r["speaker"])) for r in data]


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speakers(cues: list[Cue], turns: list[tuple[float, float, str]]) -> None:
    """Label each transcript cue with the diarization speaker of max time overlap."""
    if not turns:
        return
    for cue in cues:
        best_label = None
        best_ov = 0.0
        for t0, t1, label in turns:
            ov = overlap(cue.start, cue.end, t0, t1)
            if ov > best_ov:
                best_ov = ov
                best_label = label
        cue.speaker = best_label


def sample_cues_for_speaker(cues: list[Cue], interval_sec: float) -> list[Cue]:
    mine = [c for c in cues if c.speaker and (c.text or "").strip()]
    if not mine:
        return []
    picked: list[Cue] = [mine[0]]
    next_at = mine[0].start + max(1.0, interval_sec)
    for cue in mine[1:]:
        if cue.start >= next_at:
            picked.append(cue)
            next_at = cue.start + max(1.0, interval_sec)
    if len(picked) == 1 and len(mine) > 1:
        picked.append(mine[len(mine) // 2])
        if mine[-1] not in picked:
            picked.append(mine[-1])
    return picked


def play_clip(audio_path: Path, start: float, duration: float = 4.0) -> None:
    ffplay = shutil.which("ffplay")
    if not ffplay:
        return
    cmd = [
        ffplay,
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, start):.2f}",
        "-t",
        f"{duration:.2f}",
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, check=False)
    except OSError:
        pass


def prompt_speaker_names(
    cues: list[Cue],
    audio_path: Path,
    interval_sec: float,
    play: bool,
    preset: dict[str, str] | None = None,
) -> dict[str, str]:
    by_speaker: dict[str, list[Cue]] = defaultdict(list)
    for cue in cues:
        if cue.speaker:
            by_speaker[cue.speaker].append(cue)

    labels = sorted(by_speaker.keys(), key=lambda s: (len(s), s))
    print()
    print(f"Detected {len(labels)} speaker(s).")
    if not labels:
        return {}

    mapping: dict[str, str] = {}
    preset = preset or {}

    for i, label in enumerate(labels, start=1):
        samples = sample_cues_for_speaker(by_speaker[label], interval_sec)
        talk_sec = sum(max(0.0, c.end - c.start) for c in by_speaker[label])
        print()
        print("=" * 60)
        print(f"Speaker {i}/{len(labels)}  [{label}]  ~{format_clock(talk_sec)} of speech")
        print(f"Sample lines every ~{int(interval_sec)}s:")
        for cue in samples:
            snippet = (cue.text or "").strip()
            if len(snippet) > 100:
                snippet = snippet[:97] + "..."
            print(f"  [{format_clock(cue.start)}] {snippet}")

        if play and samples:
            print("  Playing a short sample...")
            play_clip(audio_path, samples[0].start)

        if label in preset and preset[label].strip():
            name = preset[label].strip()
            print(f"  Using preset name: {name}")
        else:
            while True:
                raw = input(f"  Name for this speaker (Enter to keep {label}): ").strip()
                name = raw or label
                if name:
                    break
        mapping[label] = name

    return mapping


def apply_names(cues: list[Cue], mapping: dict[str, str]) -> None:
    for cue in cues:
        if cue.speaker and cue.speaker in mapping:
            cue.speaker = mapping[cue.speaker]


def ffmpeg_to_wav(audio_path: Path, wav_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    conv = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if conv.returncode != 0:
        print(conv.stderr[-2000:], file=sys.stderr)
        print("ERROR: ffmpeg failed to prepare audio for diarization", file=sys.stderr)
        raise SystemExit(1)


def load_wav_dict(wav_path: Path) -> dict:
    """
    Load a PCM wav into the in-memory dict pyannote accepts, bypassing broken
    Windows torchcodec/FFmpeg DLL loading.
    """
    import numpy as np
    import torch

    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise RuntimeError(f"unsupported WAV sample width: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    waveform = torch.from_numpy(np.ascontiguousarray(audio)).unsqueeze(0)  # (1, time)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def run_diarization(audio_path: Path, device: str, hf_token: str | None) -> list[tuple[float, float, str]]:
    """
    Run pyannote speaker-diarization-community-1.
    Returns list of (start, end, SPEAKER_XX).
    Feeds waveform in-memory so Windows torchcodec is never touched.
    """
    try:
        import torch
        from pyannote.audio import Pipeline
        from pyannote.core import Annotation
    except ImportError:
        print(
            "ERROR: speaker mode needs extra packages.\n"
            "  .\\.venv\\Scripts\\pip.exe install -r requirements-speakers.txt",
            file=sys.stderr,
        )
        raise SystemExit(2)

    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        print(
            "ERROR: Hugging Face token required for diarization.\n"
            "  1. Accept model terms:\n"
            "       https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "  2. Put HF_TOKEN=hf_... in the repo .env",
            file=sys.stderr,
        )
        raise SystemExit(2)

    model_id = "pyannote/speaker-diarization-community-1"
    print(f"Loading diarization model {model_id}...")
    try:
        pipeline = Pipeline.from_pretrained(model_id, token=token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(model_id, use_auth_token=token)

    torch_device = torch.device("cuda" if device == "cuda" and torch.cuda.is_available() else "cpu")
    if hasattr(pipeline, "to"):
        pipeline.to(torch_device)
    print(f"Diarizing on {torch_device} (in-memory waveform, no torchcodec)...")

    with tempfile.TemporaryDirectory(prefix="ow-diarize-") as tmp:
        wav_path = Path(tmp) / "audio.wav"
        print("Converting audio with ffmpeg...")
        ffmpeg_to_wav(audio_path, wav_path)
        print("Loading WAV into memory...")
        audio_dict = load_wav_dict(wav_path)
        print(f"Waveform shape={tuple(audio_dict['waveform'].shape)} sr={audio_dict['sample_rate']}")
        output = pipeline(audio_dict)

    if isinstance(output, Annotation):
        annotation = output
    elif hasattr(output, "speaker_diarization"):
        annotation = output.speaker_diarization
    else:
        print(f"ERROR: unexpected diarization output type: {type(output)}", file=sys.stderr)
        raise SystemExit(1)

    turns: list[tuple[float, float, str]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append((float(turn.start), float(turn.end), str(speaker)))
    turns.sort(key=lambda t: t[0])
    print(f"Diarization found {len({t[2] for t in turns})} speaker label(s), {len(turns)} turn(s)")
    return turns


def parse_names_arg(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if "=" in raw:
        out: dict[str, str] = {}
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                print(f"WARNING: ignoring name entry without '=': {part}", file=sys.stderr)
                continue
            key, val = part.split("=", 1)
            out[key.strip()] = val.strip()
        return out
    return {"__positional__": raw}


def resolve_positional_names(labels: list[str], raw_list: str) -> dict[str, str]:
    names = [n.strip() for n in raw_list.split(",") if n.strip()]
    out: dict[str, str] = {}
    for label, name in zip(labels, names):
        out[label] = name
    if len(names) < len(labels):
        print(
            f"NOTE: --names provided {len(names)} name(s) for {len(labels)} speaker(s); "
            "remaining labels kept as-is.",
            file=sys.stderr,
        )
    elif len(names) > len(labels):
        print(
            f"NOTE: --names provided {len(names)} name(s) but only {len(labels)} speaker(s); extras ignored.",
            file=sys.stderr,
        )
    return out


def resolve_input(root: Path, arg: str | None) -> Path:
    if arg:
        in_path = Path(arg).expanduser().resolve()
        if not in_path.exists():
            print(f"ERROR: file not found: {in_path}", file=sys.stderr)
            raise SystemExit(1)
        return in_path

    candidates = []
    for folder in (root / "input", root):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in {
                ".m4a",
                ".mp3",
                ".wav",
                ".mp4",
                ".mkv",
                ".flac",
                ".ogg",
                ".webm",
                ".aac",
            }:
                candidates.append(p)
    candidates = sorted(set(candidates), key=lambda p: p.name.lower())
    if not candidates:
        print("Usage: transcribe_to_srt.py <audio_or_video> [--model medium] [--speakers]")
        raise SystemExit(1)
    print(f"No input arg — using {candidates[0]}")
    return candidates[0].resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audio/video -> SRT transcript (faster-whisper)")
    parser.add_argument("input", nargs="?", help="Audio/video file path")
    parser.add_argument("-o", "--output", help="Output .srt path (default: output/<name>.srt)")
    parser.add_argument(
        "--model",
        default="medium",
        help="Whisper model: tiny, base, small, medium, large-v3, distil-large-v3 (default: medium)",
    )
    parser.add_argument("--language", default=None, help="Language code, e.g. en, fr (auto if omitted)")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Inference device (default: auto)",
    )
    parser.add_argument("--txt", action="store_true", help="Also write a plain .txt transcript")
    parser.add_argument(
        "--speakers",
        action="store_true",
        help="Detect speakers, ask you to name them, write names into the SRT",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse existing output SRT/cues/diarization cache (skip Whisper). Implied by --speakers.",
    )
    parser.add_argument(
        "--force-transcribe",
        action="store_true",
        help="Always re-run Whisper even if a cached transcript exists",
    )
    parser.add_argument(
        "--force-diarize",
        action="store_true",
        help="Always re-run diarization even if a turns cache exists",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=120.0,
        help="Seconds between sample lines shown when naming a speaker (default: 120)",
    )
    parser.add_argument(
        "--play-samples",
        action="store_true",
        help="Play a short audio clip (ffplay) when asking for each speaker name",
    )
    parser.add_argument(
        "--names",
        default=None,
        help='Skip prompts: "Alice,Bob" (sorted speaker order) or "SPEAKER_00=Alice,SPEAKER_01=Bob"',
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="Hugging Face token for pyannote (else HF_TOKEN env)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    repo_root = root.parent
    load_dotenv_files(root / ".env", repo_root / ".env")

    path_bits = [str(root)]
    nvidia_root = root / ".venv" / "Lib" / "site-packages" / "nvidia"
    if nvidia_root.exists():
        path_bits.extend(str(p) for p in nvidia_root.glob("*/bin") if p.is_dir())
    os.environ["PATH"] = os.pathsep.join(path_bits) + os.pathsep + os.environ.get("PATH", "")

    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found. Place ffmpeg.exe next to this script.", file=sys.stderr)
        return 1

    in_path = resolve_input(root, args.input)

    out_dir = root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_srt = Path(args.output).expanduser().resolve() if args.output else out_dir / f"{in_path.stem}.srt"
    cues_cache = out_srt.with_suffix(".cues.json")
    turns_cache = out_srt.with_suffix(".diarization.json")

    # Prefer matching stem SRT; also accept output/Test.srt if audio is Recording (4).m4a copy case
    reuse = args.reuse or (args.speakers and not args.force_transcribe)
    cues: list[Cue] | None = None
    if reuse and not args.force_transcribe:
        if cues_cache.is_file():
            print(f"Reusing transcript cache: {cues_cache.name}")
            cues = load_cues_cache(cues_cache)
        elif out_srt.is_file():
            print(f"Reusing existing SRT (skip Whisper): {out_srt.name}")
            cues = read_srt(out_srt)
        else:
            # Common case: transcribed as Test.srt from Recording (4).m4a
            alt = out_dir / "Test.srt"
            if in_path.stem != "Test" and alt.is_file():
                print(f"Reusing existing SRT (skip Whisper): {alt.name}")
                cues = read_srt(alt)

    if cues is None:
        device = args.device
        compute_type = "float16"
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if device == "cpu":
            compute_type = "int8"

        print(f"Model={args.model}  device={device}  compute={compute_type}")
        print("Loading model (first run downloads weights)...")
        model = WhisperModel(args.model, device=device, compute_type=compute_type)

        print(f"Transcribing: {in_path}")
        segments_iter, info = model.transcribe(
            str(in_path),
            language=args.language,
            beam_size=5,
            vad_filter=True,
        )
        print(f"Detected language: {info.language} (p={info.language_probability:.2f})")
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if duration > 0:
            print(f"Audio length: {format_clock(duration)}")
        else:
            print("Audio length unknown — showing segment count only")

        cues = []
        last_pct = -1
        for seg in segments_iter:
            text = (seg.text or "").strip()
            cues.append(Cue(start=float(seg.start), end=float(seg.end), text=text))
            done = float(seg.end or 0.0)
            if duration > 0:
                pct = int(min(100.0, (done / duration) * 100.0))
                if pct != last_pct:
                    print_progress(done, duration)
                    last_pct = pct
            else:
                sys.stdout.write(f"\rSegments: {len(cues)}")
                sys.stdout.flush()

        if duration > 0:
            print_progress(duration, duration)
        sys.stdout.write("\n")
        sys.stdout.flush()
        save_cues_cache(cues_cache, cues)
        print(f"Cached transcript: {cues_cache.name}")
    else:
        # Still need a device string for diarization
        device = args.device
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        # Keep a cues cache for next time
        if not cues_cache.is_file():
            save_cues_cache(cues_cache, cues)
            print(f"Cached transcript: {cues_cache.name}")

    if args.speakers:
        if turns_cache.is_file() and not args.force_diarize:
            print(f"Reusing diarization cache: {turns_cache.name}")
            turns = load_turns_cache(turns_cache)
        else:
            turns = run_diarization(in_path, device=device, hf_token=args.hf_token)
            save_turns_cache(turns_cache, turns)
            print(f"Cached diarization: {turns_cache.name}")

        assign_speakers(cues, turns)

        names_arg = parse_names_arg(args.names)
        preset: dict[str, str] = {}
        if names_arg and "__positional__" in names_arg:
            labels = sorted({c.speaker for c in cues if c.speaker}, key=lambda s: (len(s), s))
            preset = resolve_positional_names(labels, names_arg["__positional__"])
            mapping = prompt_speaker_names(
                cues,
                in_path,
                interval_sec=args.sample_interval,
                play=args.play_samples,
                preset=preset,
            )
        elif names_arg:
            mapping = prompt_speaker_names(
                cues,
                in_path,
                interval_sec=args.sample_interval,
                play=args.play_samples,
                preset=names_arg,
            )
        else:
            mapping = prompt_speaker_names(
                cues,
                in_path,
                interval_sec=args.sample_interval,
                play=args.play_samples,
            )
        apply_names(cues, mapping)

    write_srt(cues, out_srt)
    print(f"Wrote SRT: {out_srt}")
    if args.txt:
        out_txt = out_srt.with_suffix(".txt")
        write_txt(cues, out_txt)
        print(f"Wrote TXT: {out_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
