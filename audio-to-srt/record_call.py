"""Record Windows speaker output (WASAPI loopback), then transcribe to SRT.

Typical use: join a Teams call, play audio through speakers/headphones, run this
script, Ctrl+C when the call ends — writes a WAV then runs the normal Whisper
pipeline (same as transcribe_to_srt.py).

This captures what you *hear* (remote participants / shared audio), not your mic.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path


def list_loopbacks() -> None:
    import soundcard as sc

    print("Playback devices (use these names with --loopback):")
    for sp in sc.all_speakers():
        print(f"  speaker: {sp.name}")
    print()
    print("Loopback capture targets:")
    for mic in sc.all_microphones(include_loopback=True):
        if getattr(mic, "isloopback", False):
            print(f"  loopback: {mic.name}")


def pick_loopback(name_substr: str | None):
    import soundcard as sc

    loopbacks = [m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]
    if not loopbacks:
        print("ERROR: no WASAPI loopback devices found.", file=sys.stderr)
        raise SystemExit(1)

    if name_substr:
        key = name_substr.lower()
        matches = [m for m in loopbacks if key in m.name.lower()]
        if not matches:
            print(f"ERROR: no loopback matching {name_substr!r}. Try --list-devices.", file=sys.stderr)
            raise SystemExit(1)
        if len(matches) > 1:
            print(f"Multiple matches for {name_substr!r}; using the first:")
            for m in matches:
                print(f"  - {m.name}")
        return matches[0]

    # Prefer loopback of the current default speaker
    speaker = sc.default_speaker()
    try:
        return sc.get_microphone(id=speaker.id, include_loopback=True)
    except Exception:
        pass
    for m in loopbacks:
        if m.name == speaker.name:
            return m
    return loopbacks[0]


def rms_level(mono) -> float:
    import numpy as np

    x = np.asarray(mono, dtype=np.float64)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x)))


def record_loopback(out_wav: Path, loopback_name: str | None, sample_rate: int) -> float:
    """Record until Ctrl+C. Returns duration seconds."""
    import numpy as np
    import soundfile as sf

    mic = pick_loopback(loopback_name)
    print(f"Capturing speaker output via: {mic.name}")
    print(f"Writing: {out_wav}")
    print("Join / start your Teams call, then leave this running.")
    print("Press Ctrl+C when the call ends to stop and transcribe.\n")

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    chunk_frames = sample_rate  # ~1s
    started = time.monotonic()
    last_print = 0.0

    # Open recorder with as many channels as the device wants; downmix to mono.
    channels = getattr(mic, "channels", 2) or 2
    try:
        channels = int(channels)
    except Exception:
        channels = 2

    with sf.SoundFile(
        str(out_wav),
        mode="w",
        samplerate=sample_rate,
        channels=1,
        subtype="PCM_16",
    ) as wav:
        with mic.recorder(samplerate=sample_rate, channels=channels) as rec:
            try:
                while True:
                    block = rec.record(numframes=chunk_frames)
                    arr = np.asarray(block, dtype=np.float32)
                    if arr.ndim == 1:
                        mono = arr
                    else:
                        mono = arr.mean(axis=1)
                    wav.write(mono)

                    now = time.monotonic()
                    if now - last_print >= 1.0:
                        elapsed = now - started
                        level = rms_level(mono)
                        bar = "#" * min(20, int(level * 80)) + "-" * (20 - min(20, int(level * 80)))
                        sys.stdout.write(
                            f"\rRecording {elapsed:7.1f}s  level [{bar}]  (Ctrl+C to finish)"
                        )
                        sys.stdout.flush()
                        last_print = now
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                sys.stdout.flush()
                print("Stopped capture.")

    duration = time.monotonic() - started
    size = out_wav.stat().st_size if out_wav.exists() else 0
    print(f"Saved {out_wav.name} ({size / 1_000_000:.1f} MB, ~{duration:.0f}s)")
    return duration


def run_transcribe(wav: Path, extra_args: list[str]) -> int:
    root = Path(__file__).resolve().parent
    script = root / "transcribe_to_srt.py"
    cmd = [sys.executable, str(script), str(wav), *extra_args]
    print("\nTranscribing recording…")
    print(" ", " ".join(cmd))
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record Teams/speaker output (loopback), then transcribe to SRT"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List speaker / loopback devices and exit",
    )
    parser.add_argument(
        "--loopback",
        default=None,
        help='Substring of the playback device to capture (e.g. "Chat", "Headphones")',
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=48000,
        help="Capture sample rate (default 48000)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output WAV path (default: output/call-YYYYMMDD-HHMMSS.wav)",
    )
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Only record; skip Whisper/SRT",
    )
    # Forwarded to transcribe_to_srt.py
    parser.add_argument("--model", default="medium")
    parser.add_argument("--language", default=None)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--txt", action="store_true", default=True)
    parser.add_argument("--no-txt", action="store_true", help="Do not write .txt")
    parser.add_argument("--speakers", action="store_true", help="Name speakers after transcription")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    # Same PATH trick as transcribe_to_srt for nvidia DLLs if needed later
    os.environ["PATH"] = str(root) + os.pathsep + os.environ.get("PATH", "")

    if args.list_devices:
        list_loopbacks()
        return 0

    try:
        import soundcard  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError:
        print(
            "ERROR: missing packages. Install with:\n"
            "  .\\.venv\\Scripts\\pip.exe install -r requirements-live.txt",
            file=sys.stderr,
        )
        return 2

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_wav = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (root / "output" / f"call-{stamp}.wav")
    )

    duration = record_loopback(out_wav, args.loopback, args.sample_rate)
    if duration < 1.0:
        print("Recording too short; nothing to transcribe.", file=sys.stderr)
        return 1

    if args.no_transcribe:
        print(f"Skipped transcription. WAV: {out_wav}")
        return 0

    forward: list[str] = ["--model", args.model, "--device", args.device]
    if args.language:
        forward.extend(["--language", args.language])
    if args.txt and not args.no_txt:
        forward.append("--txt")
    if args.speakers:
        forward.append("--speakers")

    return run_transcribe(out_wav, forward)


if __name__ == "__main__":
    raise SystemExit(main())
