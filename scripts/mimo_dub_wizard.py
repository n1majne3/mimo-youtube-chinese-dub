#!/usr/bin/env python3
"""Interactive CLI for Xiaomi Mimo YouTube Chinese dubbing jobs."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
TOKEN_PLAN_API_KEY_ENV = "MIMO_TOKEN_PLAN_API_KEY"
LEGACY_API_KEY_ENV = "MIMO_API_KEY"
CLASSIFICATION_MODEL = "mimo-v2.5-pro"
CONTENT_TYPES = {"auto", "solo", "interview", "narration", "multi-speaker", "music", "unknown"}

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import mimo_audio_api


@dataclass
class RunPaths:
    log: Path
    exit: Path


@dataclass
class WizardConfig:
    url: str
    job_dir: Path
    scope: str = "test"
    content_type: str = "auto"
    mode: str = "auto"
    source_video: Path | None = None
    output: Path | None = None
    clip_start: str | None = None
    clip_duration: str | None = "120s"
    base_url: str = DEFAULT_BASE_URL
    env_file: Path = Path(".env")
    chunk_duration: float = 60.0
    target_chars_per_second: float = 10.0
    pause_duration: float = 0.2
    max_tail_silence: float = 0.6
    max_turn_tail_silence: float = 0.4
    min_atempo_factor: float = 0.55
    voice_strategy: str = "voice-clone"
    voice_sample: Path | None = None
    host_voice_sample: Path | None = None
    guest_voice_sample: Path | None = None
    voice_sample_start: str | None = None
    host_sample_start: str | None = None
    guest_sample_start: str | None = None
    sample_duration: str = "12s"
    voice_prompt: str = ""
    skip_prepare: bool = False
    dry_run: bool = False


@dataclass
class VideoClassification:
    content_type: str
    recommended_mode: str
    recommended_voice_strategy: str
    confidence: float
    reason: str


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def clean_youtube_start_params(url: str) -> str:
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in {"t", "start"}]
    return urlunparse(parsed._replace(query=urlencode(query)))


def shell_quote(value: str) -> str:
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-=.,/:@%")
    if value and all(char in safe for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def printable_command(command: list[str]) -> str:
    return " ".join(shell_quote(part) for part in command)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def has_mimo_key() -> bool:
    return bool(os.environ.get(TOKEN_PLAN_API_KEY_ENV) or os.environ.get(LEGACY_API_KEY_ENV))


def current_api_key() -> str:
    return os.environ.get(TOKEN_PLAN_API_KEY_ENV) or os.environ.get(LEGACY_API_KEY_ENV) or ""


def default_job_dir(url: str) -> Path:
    parsed = urlparse(url)
    video_id = "youtube"
    for key, value in parse_qsl(parsed.query):
        if key == "v" and value:
            video_id = value
            break
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in video_id).strip("-")
    return Path("work") / f"mimo-dub-{safe or 'youtube'}"


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
    query = dict(parse_qsl(parsed.query))
    for key in ("t", "start"):
        if query.get(key):
            return parse_time_to_seconds(query[key])
    return None


def subtitle_offset_seconds(config: WizardConfig) -> float:
    if config.scope == "full":
        return 0.0
    if config.clip_start:
        return parse_time_to_seconds(config.clip_start) or 0.0
    return youtube_start_seconds(config.url) or 0.0


def content_type_to_mode(content_type: str) -> str:
    return "two-speaker" if content_type == "interview" else "single"


def default_voice_strategy_for_content_type(content_type: str) -> str:
    return "voice-design" if content_type in {"narration", "music"} else "voice-clone"


def default_voice_prompt(content_type: str, mode: str) -> str:
    if mode == "two-speaker" or content_type == "interview":
        return "使用参考音色克隆当前说话人。中文表达自然清晰，保持访谈语气，语速中等偏快，避免过度情绪化。"
    if content_type == "narration":
        return "中文旁白自然清晰，节奏稳定，沉稳可信，适合纪录片、故事或产品介绍。"
    if content_type == "solo":
        return "中文讲解自然清晰，语速中等偏快，像专业创作者在直接讲解内容。"
    if content_type == "multi-speaker":
        return "中文表达自然清晰，使用中性讲述风格覆盖多说话人内容，避免夸张表演。"
    return "中文表达自然清晰，语速中等偏快，保持原视频的信息密度和自然语气。"


def metadata_summary(metadata: dict[str, Any], subtitle_preview: str, *, max_subtitle_chars: int = 4000) -> dict[str, Any]:
    description = str(metadata.get("description") or "")
    tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
    categories = metadata.get("categories") if isinstance(metadata.get("categories"), list) else []
    return {
        "title": str(metadata.get("title") or ""),
        "description": description[:2000],
        "channel": str(metadata.get("channel") or metadata.get("uploader") or ""),
        "duration": metadata.get("duration"),
        "tags": [str(tag) for tag in tags[:20]],
        "categories": [str(category) for category in categories[:10]],
        "subtitle_preview": subtitle_preview[:max_subtitle_chars],
    }


def strip_subtitle_text(text: str, max_chars: int = 5000) -> str:
    rows: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            rows.append(line)
        if sum(len(row) for row in rows) >= max_chars:
            break
    return " ".join(rows)[:max_chars]


def parse_subtitle_timecode(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
    elif len(parts) == 2:
        hours = 0.0
        minutes = float(parts[0])
        seconds = float(parts[1])
    else:
        raise ValueError(f"Unsupported subtitle timecode: {value}")
    return hours * 3600 + minutes * 60 + seconds


def clean_subtitle_line(line: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", line)
    cleaned = cleaned.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_subtitle_cues(text: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []
    time_pattern = re.compile(r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{3})\s+-->\s+(?P<end>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{3})")

    def flush() -> None:
        nonlocal current_start, current_end, current_lines
        if current_start is not None and current_end is not None and current_lines:
            text_value = " ".join(line for line in current_lines if line)
            text_value = re.sub(r"\s+", " ", text_value).strip()
            if text_value:
                cues.append(SubtitleCue(current_start, current_end, text_value))
        current_start = None
        current_end = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE", "STYLE", "REGION")):
            continue
        match = time_pattern.search(line)
        if match:
            flush()
            current_start = parse_subtitle_timecode(match.group("start"))
            current_end = parse_subtitle_timecode(match.group("end"))
            continue
        if line.isdigit() and current_start is None:
            continue
        if current_start is not None:
            cleaned = clean_subtitle_line(line)
            if cleaned and (not current_lines or current_lines[-1] != cleaned):
                current_lines.append(cleaned)
    flush()
    return cues


def normalize_source_text(text: str) -> str:
    normalized = re.sub(r"\bopen[\s-]*code\b", "opencode", text, flags=re.IGNORECASE)
    normalized = normalized.replace("开放代码", "opencode")
    return re.sub(r"\s+", " ", normalized).strip()


def write_asr_from_subtitle_cues(
    job_dir: Path,
    chunks: list[dict[str, Any]],
    cues: list[SubtitleCue],
    *,
    subtitle_offset: float = 0.0,
) -> int:
    asr_dir = job_dir / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for chunk in chunks:
        chunk_start = float(chunk["start"]) + subtitle_offset
        chunk_end = float(chunk["end"]) + subtitle_offset
        rows: list[str] = []
        for cue in cues:
            if cue.end <= chunk_start or cue.start >= chunk_end:
                continue
            cleaned = normalize_source_text(cue.text)
            if cleaned and (not rows or rows[-1] != cleaned):
                rows.append(cleaned)
        text_value = normalize_source_text(" ".join(rows))
        if not text_value:
            continue
        output = asr_dir / f"{chunk['id']}.txt"
        if output.exists() and output.stat().st_size > 0:
            continue
        output.write_text(text_value + "\n", encoding="utf-8")
        written += 1
    return written


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


def build_chunks(duration: float, chunk_duration: float) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    count = int(math.ceil(duration / chunk_duration))
    for index in range(count):
        start = index * chunk_duration
        dur = min(chunk_duration, max(0.0, duration - start))
        if dur <= 0.05:
            continue
        chunks.append({"id": f"{index + 1:04d}", "start": start, "end": start + dur, "duration": dur})
    return chunks


def subtitle_files(job_dir: Path) -> list[Path]:
    metadata_dir = job_dir / "metadata"
    return sorted(metadata_dir.glob("subtitle*.vtt")) + sorted(metadata_dir.glob("subtitle*.srt"))


def fetch_youtube_metadata(url: str, job_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    metadata_dir = job_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    output = metadata_dir / "youtube.json"
    if output.exists():
        return json.loads(output.read_text(encoding="utf-8"))
    if dry_run:
        payload = {"title": "", "description": "", "channel": "", "duration": None, "tags": [], "categories": []}
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    command = ["yt-dlp", "--skip-download", "--no-playlist", "--dump-json", url]
    print("+ " + printable_command(command))
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    raw = json.loads(result.stdout)
    payload = {
        "title": raw.get("title"),
        "description": raw.get("description"),
        "channel": raw.get("channel") or raw.get("uploader"),
        "duration": raw.get("duration"),
        "tags": raw.get("tags") or [],
        "categories": raw.get("categories") or [],
        "subtitles": sorted((raw.get("subtitles") or {}).keys()),
        "automatic_captions": sorted((raw.get("automatic_captions") or {}).keys()),
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def fetch_subtitle_preview(url: str, job_dir: Path, *, dry_run: bool = False) -> str:
    metadata_dir = job_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    preview_path = metadata_dir / "subtitle_preview.txt"
    if preview_path.exists():
        return preview_path.read_text(encoding="utf-8")
    if dry_run:
        preview_path.write_text("", encoding="utf-8")
        return ""
    command = [
        "yt-dlp",
        "--skip-download",
        "--no-playlist",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "en.*,en",
        "--sub-format",
        "vtt/best",
        "-o",
        str(metadata_dir / "subtitle.%(ext)s"),
        url,
    ]
    print("+ " + printable_command(command))
    subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    subtitle_files = sorted(metadata_dir.glob("subtitle*.vtt")) + sorted(metadata_dir.glob("subtitle*.srt"))
    text = ""
    for subtitle_file in subtitle_files:
        text = strip_subtitle_text(subtitle_file.read_text(encoding="utf-8", errors="replace"))
        if text:
            break
    preview_path.write_text(text, encoding="utf-8")
    return text


def seed_asr_from_available_subtitles(config: WizardConfig) -> int:
    files = subtitle_files(config.job_dir)
    if not files:
        return 0
    if not config.source_video:
        return 0
    duration = ffprobe_duration(config.source_video)
    chunks = build_chunks(duration, config.chunk_duration)
    offset = subtitle_offset_seconds(config)
    for subtitle_file in files:
        cues = parse_subtitle_cues(subtitle_file.read_text(encoding="utf-8", errors="replace"))
        if not cues:
            continue
        written = write_asr_from_subtitle_cues(config.job_dir, chunks, cues, subtitle_offset=offset)
        if written:
            manifest = {
                "source": str(subtitle_file),
                "subtitle_offset": offset,
                "chunks": len(chunks),
                "written_asr_files": written,
            }
            metadata_dir = config.job_dir / "metadata"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            (metadata_dir / "subtitle_asr_manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"字幕已写入 ASR 缓存: {written}/{len(chunks)} chunks from {subtitle_file}")
            return written
    return 0


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Expected JSON object, got: {text[:300]}")
    return json.loads(cleaned[start : end + 1])


def normalize_classification(payload: dict[str, Any]) -> VideoClassification:
    content_type = str(payload.get("content_type") or "unknown").strip()
    if content_type not in CONTENT_TYPES - {"auto"}:
        content_type = "unknown"
    recommended_mode = str(payload.get("recommended_mode") or content_type_to_mode(content_type)).strip()
    if recommended_mode not in {"single", "two-speaker"}:
        recommended_mode = content_type_to_mode(content_type)
    if content_type != "interview" and recommended_mode == "two-speaker":
        recommended_mode = "single"
    voice_strategy = str(payload.get("recommended_voice_strategy") or default_voice_strategy_for_content_type(content_type)).strip()
    if voice_strategy not in {"voice-clone", "voice-design"}:
        voice_strategy = default_voice_strategy_for_content_type(content_type)
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    reason = str(payload.get("reason") or "No reason provided.").strip()
    return VideoClassification(
        content_type=content_type,
        recommended_mode=recommended_mode,
        recommended_voice_strategy=voice_strategy,
        confidence=confidence,
        reason=reason,
    )


def heuristic_classification(summary: dict[str, Any]) -> VideoClassification:
    text = " ".join(
        [
            str(summary.get("title") or ""),
            str(summary.get("description") or ""),
            str(summary.get("subtitle_preview") or ""),
        ]
    ).lower()
    if any(word in text for word in ("interview", "podcast", "conversation", "q&a", "with ")):
        return VideoClassification("interview", "two-speaker", "voice-clone", 0.55, "Metadata suggests an interview or conversation.")
    if any(word in text for word in ("documentary", "narration", "story", "trailer")):
        return VideoClassification("narration", "single", "voice-design", 0.55, "Metadata suggests narration.")
    if any(word in text for word in ("tutorial", "guide", "lecture", "keynote", "explained", "how to")):
        return VideoClassification("solo", "single", "voice-clone", 0.55, "Metadata suggests one-speaker explanation.")
    return VideoClassification("unknown", "single", "voice-clone", 0.35, "Could not confidently infer video type from metadata.")


def classify_video(summary: dict[str, Any], *, api_key: str, base_url: str, dry_run: bool = False) -> VideoClassification:
    if dry_run or not api_key:
        return heuristic_classification(summary)
    payload = {
        "model": CLASSIFICATION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是视频中文配音流程分类器。根据 YouTube 标题、描述和字幕预览判断视频类型，"
                    "只输出严格 JSON，不要 markdown，不要解释。"
                    "content_type 只能是 solo、interview、narration、multi-speaker、music、unknown。"
                    "recommended_mode 只能是 single 或 two-speaker。只有明确双人访谈、播客、问答时才选 two-speaker；"
                    "教程、演讲、产品介绍、旁白、纪录片、vlog、游戏解说、多人但无法稳定区分说话人的视频都选 single。"
                    "recommended_voice_strategy 只能是 voice-clone 或 voice-design。"
                    "输出格式：{\"content_type\":\"...\",\"recommended_mode\":\"...\",\"recommended_voice_strategy\":\"...\","
                    "\"confidence\":0.0,\"reason\":\"...\"}"
                ),
            },
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    response = mimo_audio_api.mimo_post(payload, api_key=api_key, base_url=base_url)
    message = mimo_audio_api.extract_message(response)
    content = message.get("content")
    if not isinstance(content, str):
        return heuristic_classification(summary)
    return normalize_classification(extract_json_object(content))


def apply_classification(config: WizardConfig, classification: VideoClassification) -> None:
    if config.content_type == "auto":
        config.content_type = classification.content_type
    if config.mode == "auto":
        config.mode = classification.recommended_mode if config.content_type == classification.content_type else content_type_to_mode(config.content_type)
    if config.voice_strategy == "auto":
        config.voice_strategy = (
            classification.recommended_voice_strategy
            if config.content_type == classification.content_type
            else default_voice_strategy_for_content_type(config.content_type)
        )
    if not config.voice_prompt:
        config.voice_prompt = default_voice_prompt(config.content_type, config.mode)


def write_classification(job_dir: Path, summary: dict[str, Any], classification: VideoClassification) -> None:
    metadata_dir = job_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "classification_input.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (metadata_dir / "classification.json").write_text(
        json.dumps(asdict(classification), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def maybe_confirm_classification(config: WizardConfig, classification: VideoClassification) -> None:
    print(
        "自动判断: "
        f"type={classification.content_type}, mode={classification.recommended_mode}, "
        f"voice={classification.recommended_voice_strategy}, confidence={classification.confidence:.2f}"
    )
    print("原因: " + classification.reason)
    if not sys.stdin.isatty() or classification.confidence >= 0.7:
        return
    if ask_yes_no("置信度偏低，要手动覆盖视频类型/声线模式吗", default=False):
        config.content_type = ask(
            "Content type",
            config.content_type,
            CONTENT_TYPES - {"auto"},
        )
        config.mode = ask("Voice mode", config.mode, {"single", "two-speaker"})
        config.voice_strategy = ask("Voice strategy", config.voice_strategy, {"voice-clone", "voice-design"})
        config.voice_prompt = default_voice_prompt(config.content_type, config.mode)


def ask(prompt: str, default: str | None = None, choices: set[str] | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default is not None:
            value = default
        if not value and required:
            print("必填。")
            continue
        if choices and value not in choices:
            print("可选值: " + ", ".join(sorted(choices)))
            continue
        return value


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{default_text}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def build_prepare_command(config: WizardConfig) -> list[str]:
    url = clean_youtube_start_params(config.url) if config.scope == "full" else config.url
    command = [
        sys.executable,
        str(SCRIPT_DIR / "youtube_dub_pipeline.py"),
        "prepare",
        "--url",
        url,
        "--out-dir",
        str(config.job_dir),
    ]
    if config.scope == "test":
        if config.clip_start:
            command += ["--clip-start", config.clip_start]
        if config.clip_duration:
            command += ["--clip-duration", config.clip_duration]
    elif config.scope == "custom":
        if config.clip_start:
            command += ["--clip-start", config.clip_start]
        if config.clip_duration:
            command += ["--clip-duration", config.clip_duration]
    return command


def default_source_video(config: WizardConfig) -> Path:
    job_json = config.job_dir / "job.json"
    if job_json.exists():
        payload = json.loads(job_json.read_text(encoding="utf-8"))
        source = Path(payload["paths"]["source_video"])
        return source if source.is_absolute() else config.job_dir / source
    if (config.job_dir / "source_clip.mp4").exists():
        return config.job_dir / "source_clip.mp4"
    return config.job_dir / "source.mp4"


def default_output(config: WizardConfig) -> Path:
    if config.output:
        return config.output
    name = "two_speaker_dub.mp4" if config.mode == "two-speaker" else "chinese_dub.mp4"
    return config.job_dir / "output" / name


def build_dub_command(config: WizardConfig) -> list[str]:
    source_video = config.source_video or default_source_video(config)
    output = default_output(config)
    if config.mode == "two-speaker":
        command = [
            sys.executable,
            str(SCRIPT_DIR / "two_speaker_mimo_dub.py"),
            "--source-video",
            str(source_video),
            "--job-dir",
            str(config.job_dir),
            "--chunk-duration",
            f"{config.chunk_duration:g}",
            "--output",
            str(output),
            "--base-url",
            config.base_url,
            "--host-voice-sample",
            str(config.host_voice_sample or config.job_dir / "mimo" / "host_sample.wav"),
            "--guest-voice-sample",
            str(config.guest_voice_sample or config.job_dir / "mimo" / "guest_sample.wav"),
            "--target-chars-per-second",
            f"{config.target_chars_per_second:g}",
            "--pause-duration",
            f"{config.pause_duration:g}",
            "--max-turn-tail-silence",
            f"{config.max_turn_tail_silence:g}",
            "--min-atempo-factor",
            f"{config.min_atempo_factor:g}",
            "--voice-prompt",
            config.voice_prompt,
        ]
        return command

    command = [
        sys.executable,
        str(SCRIPT_DIR / "full_mimo_dub.py"),
        "--source-video",
        str(source_video),
        "--job-dir",
        str(config.job_dir),
        "--chunk-duration",
        f"{config.chunk_duration:g}",
        "--output",
        str(output),
        "--base-url",
        config.base_url,
        "--target-chars-per-second",
        f"{config.target_chars_per_second:g}",
        "--max-tail-silence",
        f"{config.max_tail_silence:g}",
        "--min-atempo-factor",
        f"{config.min_atempo_factor:g}",
        "--voice-strategy",
        config.voice_strategy,
        "--voice-prompt",
        config.voice_prompt,
    ]
    if config.voice_strategy == "voice-clone":
        command += ["--voice-sample", str(config.voice_sample or config.job_dir / "mimo" / "voice_sample.wav")]
    return command


def run_paths(config: WizardConfig) -> RunPaths:
    return RunPaths(log=config.job_dir / "run.log", exit=config.job_dir / "run.exit")


def run_simple(command: list[str], *, dry_run: bool = False) -> int:
    print("+ " + printable_command(command))
    if dry_run:
        return 0
    return subprocess.run(command).returncode


def run_blocking(command: list[str], paths: RunPaths, *, dry_run: bool = False) -> int:
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    print("阻断式运行，详细日志写入: " + str(paths.log))
    print("+ " + printable_command(command))
    if dry_run:
        paths.log.write_text(
            "=== Mimo dub wizard dry run: " + datetime.now().isoformat(timespec="seconds") + " ===\n"
            "+ " + printable_command(command) + "\n",
            encoding="utf-8",
        )
        paths.exit.write_text("0\n", encoding="utf-8")
        return 0

    with paths.log.open("a", encoding="utf-8") as log_file:
        log_file.write("\n=== Mimo dub wizard run: " + datetime.now().isoformat(timespec="seconds") + " ===\n")
        log_file.write("+ " + printable_command(command) + "\n")
        log_file.flush()
        completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT)
    paths.exit.write_text(str(completed.returncode) + "\n", encoding="utf-8")
    return completed.returncode


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ffmpeg_extract_sample(source: Path, output: Path, start: str, duration: str, *, dry_run: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        start,
        "-i",
        str(source),
        "-t",
        duration,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    code = run_simple(command, dry_run=dry_run)
    if code != 0:
        raise SystemExit(f"Voice sample extraction failed: {output}")


def ensure_voice_samples(config: WizardConfig) -> None:
    source = config.source_video or default_source_video(config)
    if config.mode == "two-speaker":
        config.host_voice_sample = config.host_voice_sample or config.job_dir / "mimo" / "host_sample.wav"
        config.guest_voice_sample = config.guest_voice_sample or config.job_dir / "mimo" / "guest_sample.wav"
        if config.host_sample_start and not config.host_voice_sample.exists():
            ffmpeg_extract_sample(source, config.host_voice_sample, config.host_sample_start, config.sample_duration, dry_run=config.dry_run)
        if config.guest_sample_start and not config.guest_voice_sample.exists():
            ffmpeg_extract_sample(source, config.guest_voice_sample, config.guest_sample_start, config.sample_duration, dry_run=config.dry_run)
        missing = [path for path in (config.host_voice_sample, config.guest_voice_sample) if not path.exists() and not config.dry_run]
        if missing:
            raise SystemExit("Missing voice sample(s): " + ", ".join(str(path) for path in missing))
        return

    if config.voice_strategy == "voice-clone":
        config.voice_sample = config.voice_sample or config.job_dir / "mimo" / "voice_sample.wav"
        if config.voice_sample_start and not config.voice_sample.exists():
            ffmpeg_extract_sample(source, config.voice_sample, config.voice_sample_start, config.sample_duration, dry_run=config.dry_run)
        if not config.voice_sample.exists() and not config.dry_run:
            raise SystemExit(f"Missing voice sample: {config.voice_sample}")


def verify_output(output: Path, *, dry_run: bool = False) -> None:
    print("验证输出: " + str(output))
    if dry_run:
        return
    if not output.exists():
        raise SystemExit(f"Output video not found: {output}")
    ffprobe = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size",
        "-show_entries",
        "stream=codec_type,codec_name,duration,width,height,sample_rate,channels",
        "-of",
        "json",
        str(output),
    ]
    result = subprocess.run(ffprobe, check=True, text=True, capture_output=True)
    payload = json.loads(result.stdout)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    decode = ["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"]
    subprocess.run(decode, check=True)


def tail_log(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def config_from_args(args: argparse.Namespace) -> WizardConfig:
    if args.url:
        url = args.url
    elif sys.stdin.isatty():
        url = ask("YouTube URL", required=True)
    else:
        raise SystemExit("--url is required in non-interactive mode.")

    default_dir = str(default_job_dir(url))
    job_dir = Path(args.job_dir or (ask("Job directory", default_dir) if sys.stdin.isatty() else default_dir)).expanduser()

    scope = args.scope
    if not scope and sys.stdin.isatty():
        scope = ask("Scope: test/full/custom", "test", {"test", "full", "custom"})
    scope = scope or "test"

    clip_start = args.clip_start
    clip_duration = args.clip_duration
    if scope == "test" and clip_duration is None:
        clip_duration = "120s"
    if scope == "custom" and sys.stdin.isatty():
        clip_start = clip_start or ask("Clip start, e.g. 3157s", "0s")
        clip_duration = clip_duration or ask("Clip duration, e.g. 120s", "120s")

    content_type = args.content_type
    if not content_type and sys.stdin.isatty():
        content_type = ask("Content type override", "auto", CONTENT_TYPES)
    content_type = content_type or "auto"

    mode = args.mode
    if not mode and sys.stdin.isatty():
        mode = ask("Voice mode override", "auto", {"auto", "single", "two-speaker"})
    mode = mode or "auto"

    voice_strategy = args.voice_strategy
    if not voice_strategy and sys.stdin.isatty():
        voice_strategy = ask("Voice strategy override", "auto", {"auto", "voice-clone", "voice-design"})
    voice_strategy = voice_strategy or "auto"

    config = WizardConfig(
        url=url,
        job_dir=job_dir,
        scope=scope,
        content_type=content_type,
        mode=mode,
        clip_start=clip_start,
        clip_duration=clip_duration,
        base_url=args.base_url or os.environ.get("MIMO_API_BASE_URL") or DEFAULT_BASE_URL,
        env_file=Path(args.env_file).expanduser(),
        chunk_duration=args.chunk_duration,
        target_chars_per_second=args.target_chars_per_second,
        pause_duration=args.pause_duration,
        max_tail_silence=args.max_tail_silence,
        max_turn_tail_silence=args.max_turn_tail_silence,
        min_atempo_factor=args.min_atempo_factor,
        voice_strategy=voice_strategy,
        source_video=Path(args.source_video).expanduser() if args.source_video else None,
        output=Path(args.output).expanduser() if args.output else None,
        voice_sample=Path(args.voice_sample).expanduser() if args.voice_sample else None,
        host_voice_sample=Path(args.host_voice_sample).expanduser() if args.host_voice_sample else None,
        guest_voice_sample=Path(args.guest_voice_sample).expanduser() if args.guest_voice_sample else None,
        voice_sample_start=args.voice_sample_start,
        host_sample_start=args.host_sample_start,
        guest_sample_start=args.guest_sample_start,
        sample_duration=args.sample_duration,
        voice_prompt=args.voice_prompt or "",
        skip_prepare=args.skip_prepare,
        dry_run=args.dry_run,
    )

    return config


def prompt_voice_samples(config: WizardConfig, args: argparse.Namespace) -> None:
    needs_clone = config.mode == "two-speaker" or config.voice_strategy == "voice-clone"
    if needs_clone and not config.dry_run and sys.stdin.isatty():
        if not ask_yes_no("确认你有权或已获许可使用/克隆这些声线", default=False):
            raise SystemExit("Voice clone consent was not confirmed.")

    if not sys.stdin.isatty():
        return

    if config.mode == "two-speaker":
        if not config.host_voice_sample:
            value = ask("Host voice sample path, blank to extract from source", "")
            config.host_voice_sample = Path(value).expanduser() if value else config.job_dir / "mimo" / "host_sample.wav"
        if not config.guest_voice_sample:
            value = ask("Guest voice sample path, blank to extract from source", "")
            config.guest_voice_sample = Path(value).expanduser() if value else config.job_dir / "mimo" / "guest_sample.wav"
        if not args.host_sample_start and not config.host_voice_sample.exists():
            config.host_sample_start = ask("Host sample start time", "70s")
        if not args.guest_sample_start and not config.guest_voice_sample.exists():
            config.guest_sample_start = ask("Guest sample start time", "245s")
    elif config.voice_strategy == "voice-clone":
        if not config.voice_sample:
            value = ask("Voice sample path, blank to extract from source", "")
            config.voice_sample = Path(value).expanduser() if value else config.job_dir / "mimo" / "voice_sample.wav"
        if not args.voice_sample_start and not config.voice_sample.exists():
            config.voice_sample_start = ask("Voice sample start time", "70s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--job-dir")
    parser.add_argument("--scope", choices=["test", "full", "custom"])
    parser.add_argument("--clip-start")
    parser.add_argument("--clip-duration")
    parser.add_argument("--content-type", choices=sorted(CONTENT_TYPES))
    parser.add_argument("--mode", choices=["auto", "single", "two-speaker"])
    parser.add_argument("--source-video")
    parser.add_argument("--output")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url")
    parser.add_argument("--chunk-duration", type=float, default=60.0)
    parser.add_argument("--target-chars-per-second", type=float, default=10.0)
    parser.add_argument("--pause-duration", type=float, default=0.2)
    parser.add_argument("--max-tail-silence", type=float, default=0.6)
    parser.add_argument("--max-turn-tail-silence", type=float, default=0.4)
    parser.add_argument("--min-atempo-factor", type=float, default=0.55)
    parser.add_argument("--voice-strategy", choices=["auto", "voice-clone", "voice-design"])
    parser.add_argument("--voice-sample")
    parser.add_argument("--host-voice-sample")
    parser.add_argument("--guest-voice-sample")
    parser.add_argument("--voice-sample-start")
    parser.add_argument("--host-sample-start")
    parser.add_argument("--guest-sample-start")
    parser.add_argument("--sample-duration", default="12s")
    parser.add_argument(
        "--voice-prompt",
        default="",
    )
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = config_from_args(args)
    load_env_file(config.env_file)
    if not config.dry_run and not has_mimo_key():
        raise SystemExit(f"{TOKEN_PLAN_API_KEY_ENV} is required in {config.env_file} or the environment.")

    config.job_dir.mkdir(parents=True, exist_ok=True)

    if config.content_type == "auto" or config.mode == "auto" or config.voice_strategy == "auto":
        metadata = fetch_youtube_metadata(config.url, config.job_dir, dry_run=config.dry_run)
        subtitle_preview = fetch_subtitle_preview(config.url, config.job_dir, dry_run=config.dry_run)
        summary = metadata_summary(metadata, subtitle_preview)
        classification = classify_video(
            summary,
            api_key=current_api_key(),
            base_url=config.base_url,
            dry_run=config.dry_run,
        )
        write_classification(config.job_dir, summary, classification)
        apply_classification(config, classification)
        maybe_confirm_classification(config, classification)
    else:
        if not config.voice_prompt:
            config.voice_prompt = default_voice_prompt(config.content_type, config.mode)

    prompt_voice_samples(config, args)

    if not config.skip_prepare and not config.source_video:
        code = run_simple(build_prepare_command(config), dry_run=config.dry_run)
        if code != 0:
            return code
        config.source_video = default_source_video(config)
    elif not config.source_video:
        config.source_video = default_source_video(config)

    if not config.dry_run:
        seed_asr_from_available_subtitles(config)

    ensure_voice_samples(config)

    command = build_dub_command(config)
    paths = run_paths(config)
    code = run_blocking(command, paths, dry_run=config.dry_run)
    if code != 0:
        print(f"Dub command failed with exit code {code}.")
        print(f"Log: {paths.log}")
        recent = tail_log(paths.log)
        if recent:
            print("\nRecent log lines:\n" + recent)
        return code

    output = default_output(config)
    verify_output(output, dry_run=config.dry_run)
    if config.dry_run:
        print("\nDry run 完成；未下载、未调用 API、未生成视频。计划输出路径: " + str(output))
    else:
        print("\n完成。输出视频: " + str(output))
    print("日志: " + str(paths.log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
