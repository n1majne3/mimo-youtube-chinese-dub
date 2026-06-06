#!/usr/bin/env python3
"""Media helper for YouTube-to-Chinese Mimo dubbing jobs.

This script handles deterministic local media steps. It intentionally does not
guess Xiaomi Mimo endpoints; use the skill reference to implement API calls.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def parse_time_to_seconds(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip().lower()
    if text.isdigit():
        return float(text)
    total = 0.0
    number = ""
    multipliers = {"h": 3600, "m": 60, "s": 1}
    for char in text:
        if char.isdigit() or char == ".":
            number += char
            continue
        if char in multipliers and number:
            total += float(number) * multipliers[char]
            number = ""
        else:
            raise ValueError(f"Unsupported time value: {value}")
    if number:
        total += float(number)
    return total


def youtube_start_seconds(url: str) -> float | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("t", "start"):
        if key in query and query[key]:
            return parse_time_to_seconds(query[key][0])
    return None


def command_path(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], *, dry_run: bool = False) -> None:
    printable = " ".join(quote(part) for part in cmd)
    print(f"+ {printable}")
    if not dry_run:
        subprocess.run(cmd, check=True)


def quote(value: str) -> str:
    if not value:
        return "''"
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-=.,/:@%")
    if all(char in safe for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def require_tools(names: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        path = command_path(name)
        if path:
            found[name] = path
        else:
            missing.append(name)
    if missing:
        raise SystemExit(
            "Missing required command(s): "
            + ", ".join(missing)
            + ". Install them before running non-dry-run media steps."
        )
    return found


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


@dataclass(frozen=True)
class PreparedPaths:
    source_video: Path
    asr_audio: Path
    job_json: Path


def prepare(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for child in ("mimo", "tts", "output", "tmp"):
        (out_dir / child).mkdir(exist_ok=True)

    url_start = youtube_start_seconds(args.url)
    clip_start = parse_time_to_seconds(args.clip_start) if args.clip_start else args.clip_start_seconds
    if clip_start is None:
        clip_start = url_start
    clip_duration = parse_time_to_seconds(args.clip_duration) if args.clip_duration else None

    if not args.dry_run:
        require_tools(["yt-dlp", "ffmpeg", "ffprobe"])

    source_template = out_dir / "source.%(ext)s"
    download_cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        str(source_template),
        args.url,
    ]
    run(download_cmd, dry_run=args.dry_run)

    source_video = out_dir / "source.mp4"
    if not args.dry_run:
        candidates = sorted(out_dir.glob("source.*"))
        if not candidates:
            raise SystemExit(f"No downloaded source video found in {out_dir}")
        source_video = candidates[0]

    working_video = source_video
    if clip_start is not None or clip_duration is not None:
        working_video = out_dir / "source_clip.mp4"
        clip_cmd = ["ffmpeg", "-y"]
        if clip_start is not None:
            clip_cmd += ["-ss", f"{clip_start:.3f}"]
        clip_cmd += ["-i", str(source_video)]
        if clip_duration is not None:
            clip_cmd += ["-t", f"{clip_duration:.3f}"]
        clip_cmd += ["-c", "copy", str(working_video)]
        run(clip_cmd, dry_run=args.dry_run)

    asr_audio = out_dir / "source_16k_mono.wav"
    extract_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(working_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(asr_audio),
    ]
    run(extract_cmd, dry_run=args.dry_run)

    job = {
        "url": args.url,
        "created_by": "mimo-youtube-chinese-dub",
        "dry_run": bool(args.dry_run),
        "clip": {
            "url_start_seconds": url_start,
            "start_seconds": clip_start,
            "duration_seconds": clip_duration,
        },
        "paths": {
            "job_dir": str(out_dir),
            "source_video": str(working_video),
            "asr_audio_wav": str(asr_audio),
            "asr_segments": str(out_dir / "mimo" / "asr_segments.json"),
            "chinese_segments": str(out_dir / "segments.zh.json"),
            "voice": str(out_dir / "mimo" / "voice.json"),
            "tts_dir": str(out_dir / "tts"),
            "output_video": str(out_dir / "output" / "chinese_dub.mp4"),
        },
    }
    write_json(out_dir / "job.json", job)
    print(f"Wrote {out_dir / 'job.json'}")


def check(_: argparse.Namespace) -> None:
    payload = {
        "yt-dlp": command_path("yt-dlp"),
        "ffmpeg": command_path("ffmpeg"),
        "ffprobe": command_path("ffprobe"),
        "MIMO_TOKEN_PLAN_API_KEY": "set" if os.environ.get("MIMO_TOKEN_PLAN_API_KEY") else "missing",
        "MIMO_API_KEY": "set" if os.environ.get("MIMO_API_KEY") else "missing",
        "MIMO_API_BASE_URL": os.environ.get("MIMO_API_BASE_URL") or "missing",
    }
    print(json.dumps(payload, indent=2))


def segment_tts_path(job_dir: Path, tts_dir: Path, segment: dict[str, Any]) -> Path:
    if segment.get("tts_path"):
        path = Path(str(segment["tts_path"]))
        return path if path.is_absolute() else job_dir / path
    segment_id = str(segment["id"])
    return tts_dir / f"{segment_id}.wav"


def create_silence(path: Path, duration: float) -> None:
    if duration <= 0.01:
        return
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def assemble(args: argparse.Namespace) -> None:
    require_tools(["ffmpeg", "ffprobe"])
    job_dir = Path(args.job_dir).expanduser().resolve()
    job = read_json(job_dir / "job.json")
    paths = job["paths"]
    source_video = Path(paths["source_video"])
    if not source_video.is_absolute():
        source_video = job_dir / source_video

    segments_path = Path(args.segments) if args.segments else Path(paths["chinese_segments"])
    if not segments_path.is_absolute():
        segments_path = job_dir / segments_path
    segments = read_json(segments_path)
    if not isinstance(segments, list) or not segments:
        raise SystemExit(f"{segments_path} must contain a non-empty JSON array")

    tts_dir = Path(args.tts_dir) if args.tts_dir else Path(paths["tts_dir"])
    if not tts_dir.is_absolute():
        tts_dir = job_dir / tts_dir

    tmp_dir = job_dir / "tmp" / "assemble"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    concat_entries: list[Path] = []
    cursor = 0.0

    for index, segment in enumerate(sorted(segments, key=lambda item: float(item["start"]))):
        start = float(segment["start"])
        if start > cursor:
            silence = tmp_dir / f"silence_{index:04d}.wav"
            create_silence(silence, start - cursor)
            concat_entries.append(silence)

        tts_path = segment_tts_path(job_dir, tts_dir, segment)
        if not tts_path.exists():
            raise SystemExit(f"Missing TTS file for segment {segment.get('id')}: {tts_path}")
        concat_entries.append(tts_path)
        cursor = start + ffprobe_duration(tts_path)

    target_duration = max(
        ffprobe_duration(source_video),
        max(float(segment.get("end", 0)) for segment in segments),
    )
    if cursor < target_duration:
        silence = tmp_dir / "silence_tail.wav"
        create_silence(silence, target_duration - cursor)
        concat_entries.append(silence)

    concat_file = tmp_dir / "concat.txt"
    concat_file.write_text(
        "".join(f"file {quote(str(path))}\n" for path in concat_entries),
        encoding="utf-8",
    )
    dubbed_wav = job_dir / "output" / "dubbed_audio.wav"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:a",
            "pcm_s16le",
            str(dubbed_wav),
        ]
    )

    output = Path(args.output) if args.output else Path(paths["output_video"])
    if not output.is_absolute():
        output = job_dir / output
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.original_volume is None:
        mux_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(dubbed_wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    else:
        mux_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(dubbed_wav),
            "-filter_complex",
            f"[0:a]volume={args.original_volume}[orig];[1:a]volume=1.0[dub];"
            "[orig][dub]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    run(mux_cmd)
    print(f"Wrote {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Inspect local dependencies and Mimo env vars")
    check_parser.set_defaults(func=check)

    prepare_parser = subparsers.add_parser("prepare", help="Download video and extract ASR-ready audio")
    prepare_parser.add_argument("--url", required=True, help="YouTube URL")
    prepare_parser.add_argument("--out-dir", required=True, help="Job output directory")
    prepare_parser.add_argument("--clip-start", help="Optional clip start, e.g. 3157s or 52m37s")
    prepare_parser.add_argument("--clip-start-seconds", type=float, help=argparse.SUPPRESS)
    prepare_parser.add_argument("--clip-duration", help="Optional clip duration, e.g. 120s or 2m")
    prepare_parser.add_argument("--dry-run", action="store_true", help="Print commands and write job.json without downloading")
    prepare_parser.set_defaults(func=prepare)

    assemble_parser = subparsers.add_parser("assemble", help="Assemble per-segment TTS WAV files into a dubbed video")
    assemble_parser.add_argument("--job-dir", required=True, help="Prepared job directory containing job.json")
    assemble_parser.add_argument("--segments", help="Chinese segment JSON path; defaults to job.json paths.chinese_segments")
    assemble_parser.add_argument("--tts-dir", help="Directory containing per-segment WAV files; defaults to job.json paths.tts_dir")
    assemble_parser.add_argument("--output", help="Output video path; defaults to job.json paths.output_video")
    assemble_parser.add_argument(
        "--original-volume",
        type=float,
        help="Mix original audio under the dub at this volume, e.g. 0.12. Omit to replace original audio.",
    )
    assemble_parser.set_defaults(func=assemble)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
