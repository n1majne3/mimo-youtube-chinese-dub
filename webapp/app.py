#!/usr/bin/env python3
"""Local web app for Xiaomi Mimo YouTube Chinese dubbing jobs."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
JOB_ROOT = APP_DIR / "jobs"
DEFAULT_ENV_FILE = WORKSPACE_ROOT / ".env"
LOCAL_WIZARD_SCRIPT = WORKSPACE_ROOT / "scripts" / "mimo_dub_wizard.py"
LEGACY_WIZARD_SCRIPT = Path.home() / ".agents" / "skills" / "mimo-youtube-chinese-dub" / "scripts" / "mimo_dub_wizard.py"
WIZARD_SCRIPT = LOCAL_WIZARD_SCRIPT if LOCAL_WIZARD_SCRIPT.exists() else LEGACY_WIZARD_SCRIPT
TOKEN_PLAN_PROFILE = "token_plan"
PAYG_PROFILE = "payg"
TOKEN_PLAN_API_KEY_ENV = "MIMO_TOKEN_PLAN_API_KEY"
PAYG_API_KEY_ENV = "MIMO_API_KEY"
MIMO_API_BASE_URL_ENV = "MIMO_API_BASE_URL"
API_PROFILES = {
    TOKEN_PLAN_PROFILE: {
        "label": "Token Plan API",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "key_env": TOKEN_PLAN_API_KEY_ENV,
    },
    PAYG_PROFILE: {
        "label": "按量 API",
        "base_url": "https://api.xiaomimimo.com/v1",
        "key_env": PAYG_API_KEY_ENV,
    },
}
SUBTITLE_SRT_NAME = "chinese_subtitles.srt"
SUBTITLE_VTT_NAME = "chinese_subtitles.vtt"
SUBTITLE_MAX_CUE_CHARS = 44
SUBTITLE_MAX_LINE_CHARS = 22


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def python_executable() -> str:
    return sys.executable


def load_wizard():
    spec = importlib.util.spec_from_file_location("mimo_dub_wizard_webapp", WIZARD_SCRIPT)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load wizard script: {WIZARD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WIZARD = load_wizard()


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    if not path.exists():
        return {}
    values: dict[str, str] = {}
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
        values[key] = value
    return values


def load_env_file(path: Path) -> None:
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)


def safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:80] or "job"


def resolve_local_path(value: str | Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def default_job_dir(url: str) -> Path:
    return JOB_ROOT / safe_slug(str(WIZARD.default_job_dir(url)).split("/")[-1])


@dataclass
class ApiSettings:
    profile: str
    source: str
    base_url: str
    key_env: str
    api_key: str
    env_file: Path
    env_file_exists: bool
    env_profiles: dict[str, bool]


def env_values_for(path: Path) -> tuple[Path, dict[str, str]]:
    env_file = resolve_local_path(path)
    values = read_env_file(env_file)
    for key in (TOKEN_PLAN_API_KEY_ENV, PAYG_API_KEY_ENV, MIMO_API_BASE_URL_ENV):
        if key in os.environ and key not in values:
            values[key] = os.environ[key]
    return env_file, values


def profile_for_key_env(key_env: str) -> str:
    for profile, meta in API_PROFILES.items():
        if meta["key_env"] == key_env:
            return profile
    return TOKEN_PLAN_PROFILE


def infer_env_profile(values: dict[str, str]) -> str | None:
    if values.get(TOKEN_PLAN_API_KEY_ENV):
        return TOKEN_PLAN_PROFILE
    if values.get(PAYG_API_KEY_ENV):
        return PAYG_PROFILE
    return None


def resolve_api_settings(payload: dict[str, Any], *, require_key: bool = False) -> ApiSettings:
    env_file, env_values = env_values_for(Path(str(payload.get("env_file") or DEFAULT_ENV_FILE)).expanduser())
    source = str(payload.get("api_key_source") or "env")
    if source not in {"env", "manual"}:
        source = "env"

    requested_profile = str(payload.get("api_profile") or "")
    if requested_profile not in API_PROFILES:
        requested_profile = ""

    env_profiles = {
        profile: bool(env_values.get(str(meta["key_env"])))
        for profile, meta in API_PROFILES.items()
    }

    if source == "manual":
        if not requested_profile:
            raise ValueError("前端输入 API key 时需要选择 API 类型。")
        profile = requested_profile
        api_key = str(payload.get("api_key") or "").strip()
    else:
        profile = requested_profile if requested_profile and env_profiles.get(requested_profile) else infer_env_profile(env_values)
        profile = profile or requested_profile or TOKEN_PLAN_PROFILE
        key_env = str(API_PROFILES[profile]["key_env"])
        api_key = env_values.get(key_env, "")

    meta = API_PROFILES[profile]
    key_env = str(meta["key_env"])
    env_base_url = env_values.get(MIMO_API_BASE_URL_ENV) if source == "env" else ""
    base_url = str(payload.get("base_url") or env_base_url or meta["base_url"])
    if require_key and not api_key:
        if source == "manual":
            raise ValueError("请输入 API key，或切回 .env。")
        raise ValueError(f"未找到 {key_env}。请在 .env 中配置，或选择临时输入。")

    return ApiSettings(
        profile=profile,
        source=source,
        base_url=base_url,
        key_env=key_env,
        api_key=api_key,
        env_file=env_file,
        env_file_exists=env_file.exists(),
        env_profiles=env_profiles,
    )


def public_api_settings(settings: ApiSettings) -> dict[str, Any]:
    return {
        "source": settings.source,
        "profile": settings.profile,
        "profile_label": API_PROFILES[settings.profile]["label"],
        "base_url": settings.base_url,
        "key_env": settings.key_env,
        "key_set": bool(settings.api_key),
        "env_file": str(settings.env_file),
        "env_file_exists": settings.env_file_exists,
        "env_profiles": settings.env_profiles,
    }


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "api_key"}


def process_env_for_api(settings: ApiSettings) -> dict[str, str]:
    env = os.environ.copy()
    env[MIMO_API_BASE_URL_ENV] = settings.base_url
    for profile, meta in API_PROFILES.items():
        key_env = str(meta["key_env"])
        if key_env != settings.key_env:
            env.pop(key_env, None)
    if settings.api_key:
        env[settings.key_env] = settings.api_key
    return env


def is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        stat = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError:
        return True
    if stat.startswith("Z"):
        return False
    return True


def build_wizard_command(payload: dict[str, Any], *, dry_run: bool = False) -> list[str]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    scope = str(payload.get("scope") or "test")
    job_dir = resolve_local_path(payload.get("job_dir") or default_job_dir(url))
    api_settings = resolve_api_settings(payload, require_key=False)
    env_file = api_settings.env_file
    command = [
        python_executable(),
        str(WIZARD_SCRIPT),
        "--url",
        url,
        "--job-dir",
        str(job_dir),
        "--scope",
        scope,
        "--env-file",
        str(env_file),
        "--base-url",
        api_settings.base_url,
        "--content-type",
        str(payload.get("content_type") or "auto"),
        "--mode",
        str(payload.get("mode") or "auto"),
        "--voice-strategy",
        str(payload.get("voice_strategy") or "auto"),
    ]
    optional_flags = {
        "--clip-start": payload.get("clip_start"),
        "--clip-duration": payload.get("clip_duration"),
        "--source-video": payload.get("source_video"),
        "--output": payload.get("output"),
        "--voice-sample": payload.get("voice_sample"),
        "--host-voice-sample": payload.get("host_voice_sample"),
        "--guest-voice-sample": payload.get("guest_voice_sample"),
        "--voice-sample-start": payload.get("voice_sample_start"),
        "--host-sample-start": payload.get("host_sample_start"),
        "--guest-sample-start": payload.get("guest_sample_start"),
        "--sample-duration": payload.get("sample_duration"),
        "--voice-prompt": payload.get("voice_prompt"),
    }
    for flag, value in optional_flags.items():
        if value not in (None, ""):
            if scope == "full" and flag in {"--clip-start", "--clip-duration"}:
                continue
            if flag in {"--source-video", "--output", "--voice-sample", "--host-voice-sample", "--guest-voice-sample"}:
                value = resolve_local_path(value)
            command += [flag, str(value)]
    numeric_defaults = {
        "--chunk-duration": payload.get("chunk_duration"),
        "--target-chars-per-second": payload.get("target_chars_per_second"),
        "--pause-duration": payload.get("pause_duration"),
        "--max-tail-silence": payload.get("max_tail_silence"),
        "--max-turn-tail-silence": payload.get("max_turn_tail_silence"),
        "--min-atempo-factor": payload.get("min_atempo_factor"),
        "--tts-workers": payload.get("tts_workers"),
    }
    for flag, value in numeric_defaults.items():
        if value not in (None, ""):
            command += [flag, str(value)]
    if payload.get("skip_prepare"):
        command.append("--skip-prepare")
    if dry_run or payload.get("dry_run"):
        command.append("--dry-run")
    return command


def output_candidates(job_dir: Path, payload: dict[str, Any]) -> list[Path]:
    if payload.get("output"):
        return [resolve_local_path(payload["output"])]
    return [
        job_dir / "output" / "chinese_dub.mp4",
        job_dir / "output" / "two_speaker_dub.mp4",
        job_dir / "output" / "full_chinese_dub.mp4",
    ]


def requires_voice_consent(payload: dict[str, Any], *, dry_run: bool) -> bool:
    if dry_run:
        return False
    mode = str(payload.get("mode") or "auto")
    voice_strategy = str(payload.get("voice_strategy") or "auto")
    if mode == "single" and voice_strategy == "voice-design":
        return False
    return mode in {"auto", "two-speaker"} or voice_strategy in {"auto", "voice-clone"}


def tail(path: Path, lines: int = 120) -> str:
    if not path.exists():
        return ""
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(rows[-lines:])


def job_log_tail(job_dir: Path, status: str, exit_code: int | None) -> str:
    run_tail = tail(job_dir / "run.log", 80)
    web_tail = tail(job_dir / "webapp.log", 80)
    if status == "complete":
        header = f"任务已完成，exit code {exit_code}。"
        if "Traceback" in run_tail or "Dub command failed" in web_tail:
            header += " 下方若出现 Traceback，是恢复前的历史失败日志；最终状态以完成标记为准。"
        return "\n".join(part for part in [header, run_tail] if part)
    return "\n".join(filter(None, [web_tail, run_tail]))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_subtitle_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\r", " ").replace("\n", " ").replace("-->", "->")
    return re.sub(r"\s+", " ", text).strip()


def hard_split_text(text: str, limit: int = SUBTITLE_MAX_CUE_CHARS) -> list[str]:
    return [text[index : index + limit].strip() for index in range(0, len(text), limit) if text[index : index + limit].strip()]


def split_subtitle_text(text: str, limit: int = SUBTITLE_MAX_CUE_CHARS) -> list[str]:
    text = clean_subtitle_text(text)
    if not text:
        return []
    rough_units = re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text) or [text]
    cues: list[str] = []
    for unit in rough_units:
        unit = unit.strip()
        if not unit:
            continue
        parts = hard_split_text(unit, limit) if len(unit) > limit else [unit]
        for part in parts:
            if cues and len(cues[-1]) + len(part) <= limit:
                cues[-1] += part
            else:
                cues.append(part)
    return cues


def wrap_subtitle_lines(text: str, limit: int = SUBTITLE_MAX_LINE_CHARS) -> str:
    text = clean_subtitle_text(text)
    if len(text) <= limit:
        return text
    split_at = min(max(limit, len(text) // 2), len(text) - 1)
    for offset in range(0, min(8, split_at)):
        left = split_at - offset
        right = split_at + offset
        if left > 0 and text[left - 1] in "，,、。！？!?；;：: ":
            split_at = left
            break
        if right < len(text) and text[right - 1] in "，,、。！？!?；;：: ":
            split_at = right
            break
    return f"{text[:split_at].strip()}\n{text[split_at:].strip()}"


def cues_for_text(text: str, start: float, end: float) -> list[SubtitleCue]:
    parts = split_subtitle_text(text)
    duration = max(0.0, end - start)
    if not parts or duration <= 0:
        return []
    weights = [max(1, len(clean_subtitle_text(part))) for part in parts]
    total_weight = float(sum(weights))
    cues: list[SubtitleCue] = []
    elapsed_weight = 0.0
    for part, weight in zip(parts, weights, strict=False):
        cue_start = start + duration * (elapsed_weight / total_weight)
        elapsed_weight += weight
        cue_end = start + duration * (elapsed_weight / total_weight)
        cues.append(SubtitleCue(cue_start, cue_end, part))
    return cues


def speaker_prefix(turn: dict[str, Any], *, show_speaker: bool) -> str:
    if not show_speaker:
        return ""
    speaker = str(turn.get("speaker") or "").strip().lower()
    if speaker == "host":
        return "主持："
    if speaker == "guest":
        return "嘉宾："
    return ""


def cues_for_segment(row: dict[str, Any]) -> list[SubtitleCue]:
    start = safe_float(row.get("start"))
    end = safe_float(row.get("end"), start + safe_float(row.get("duration")))
    if end <= start:
        return []

    text = clean_subtitle_text(row.get("text_zh"))
    if text:
        return cues_for_text(text, start, end)

    raw_turns = row.get("turns")
    if not isinstance(raw_turns, list):
        return []
    turns = [turn for turn in raw_turns if isinstance(turn, dict) and clean_subtitle_text(turn.get("text_zh"))]
    if not turns:
        return []

    speakers = {str(turn.get("speaker") or "").strip().lower() for turn in turns if turn.get("speaker")}
    show_speaker = len(speakers) > 1
    available_duration = max(0.0, end - start)
    turn_durations = [safe_float(turn.get("target_duration") or turn.get("fit_duration")) for turn in turns]
    if not any(duration > 0 for duration in turn_durations):
        weights = [max(1, len(clean_subtitle_text(turn.get("text_zh")))) for turn in turns]
        total_weight = float(sum(weights))
        turn_durations = [available_duration * weight / total_weight for weight in weights]
    else:
        total_duration = sum(max(0.0, duration) for duration in turn_durations)
        if total_duration > available_duration and total_duration > 0:
            scale = available_duration / total_duration
            turn_durations = [duration * scale for duration in turn_durations]

    cues: list[SubtitleCue] = []
    cursor = start
    for turn, duration in zip(turns, turn_durations, strict=False):
        turn_start = cursor
        turn_end = min(end, cursor + max(0.0, duration))
        text = speaker_prefix(turn, show_speaker=show_speaker) + clean_subtitle_text(turn.get("text_zh"))
        cues.extend(cues_for_text(text, turn_start, turn_end))
        cursor = turn_end
        if cursor >= end:
            break
    return cues


def subtitle_cues_from_segments(job_dir: Path) -> list[SubtitleCue]:
    segments_path = job_dir / "segments.zh.json"
    if not segments_path.exists():
        return []
    try:
        rows = json.loads(segments_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(rows, list):
        return []
    cues: list[SubtitleCue] = []
    for row in rows:
        if isinstance(row, dict):
            cues.extend(cues_for_segment(row))
    return sorted((cue for cue in cues if cue.text and cue.end > cue.start), key=lambda cue: (cue.start, cue.end))


def format_srt_time(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_time(seconds: float) -> str:
    return format_srt_time(seconds).replace(",", ".")


def render_srt(cues: list[SubtitleCue]) -> str:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend(
            [
                str(index),
                f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}",
                wrap_subtitle_lines(cue.text),
                "",
            ]
        )
    return "\n".join(lines)


def render_vtt(cues: list[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.extend(
            [
                f"{format_vtt_time(cue.start)} --> {format_vtt_time(cue.end)}",
                wrap_subtitle_lines(cue.text),
                "",
            ]
        )
    return "\n".join(lines)


def subtitle_output_paths(job_dir: Path) -> dict[str, Path]:
    output_dir = job_dir / "output"
    return {
        "srt": output_dir / SUBTITLE_SRT_NAME,
        "vtt": output_dir / SUBTITLE_VTT_NAME,
    }


def ensure_subtitles(job_dir: Path) -> dict[str, Path]:
    segments_path = job_dir / "segments.zh.json"
    paths = subtitle_output_paths(job_dir)
    existing = {kind: path for kind, path in paths.items() if path.exists()}
    if not segments_path.exists():
        return existing

    try:
        segments_mtime = segments_path.stat().st_mtime
    except OSError:
        return existing
    if all(path.exists() and path.stat().st_mtime >= segments_mtime for path in paths.values()):
        return paths

    cues = subtitle_cues_from_segments(job_dir)
    if not cues:
        return existing

    paths["srt"].parent.mkdir(parents=True, exist_ok=True)
    paths["srt"].write_text(render_srt(cues), encoding="utf-8")
    paths["vtt"].write_text(render_vtt(cues), encoding="utf-8")
    return paths


def analyze_video(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    dry_run = bool(payload.get("dry_run"))
    job_dir = resolve_local_path(payload.get("job_dir") or default_job_dir(url))
    job_dir.mkdir(parents=True, exist_ok=True)
    api_settings = resolve_api_settings(payload, require_key=False)
    metadata = WIZARD.fetch_youtube_metadata(url, job_dir, dry_run=dry_run)
    subtitle_preview = WIZARD.fetch_subtitle_preview(url, job_dir, dry_run=dry_run)
    summary = WIZARD.metadata_summary(metadata, subtitle_preview)
    classification = WIZARD.classify_video(
        summary,
        api_key=api_settings.api_key,
        base_url=api_settings.base_url,
        dry_run=dry_run,
    )
    WIZARD.write_classification(job_dir, summary, classification)
    return {
        "job_dir": str(job_dir),
        "summary": summary,
        "classification": asdict(classification),
        "subtitle_preview_chars": len(subtitle_preview),
        "api": public_api_settings(api_settings),
    }


@dataclass
class JobRecord:
    job_id: str
    job_dir: Path
    payload: dict[str, Any]
    command: list[str]
    status: str = "queued"
    pid: int | None = None


class JobManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.records: dict[str, JobRecord] = {}
        self.processes: dict[str, subprocess.Popen[str]] = {}

    def create_record(self, payload: dict[str, Any], *, dry_run: bool = False) -> JobRecord:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        job_dir = resolve_local_path(payload.get("job_dir") or default_job_dir(url))
        job_dir.mkdir(parents=True, exist_ok=True)
        api_settings = resolve_api_settings(payload, require_key=not dry_run)
        record_payload = sanitize_payload(
            {
                **payload,
                "job_dir": str(job_dir),
                "api_key_source": api_settings.source,
                "api_profile": api_settings.profile,
                "api_key_env": api_settings.key_env,
                "base_url": api_settings.base_url,
            }
        )
        job_id = safe_slug(f"{int(time.time())}-{job_dir.name}")
        command = build_wizard_command(record_payload, dry_run=dry_run)
        record = JobRecord(job_id=job_id, job_dir=job_dir, payload=record_payload, command=command)
        self.records[job_id] = record
        self._write_record(record)
        return record

    def start(self, payload: dict[str, Any], *, dry_run: bool = False) -> JobRecord:
        job_dir = resolve_local_path(payload.get("job_dir") or default_job_dir(str(payload.get("url") or "")))
        active_record = self._active_record_for_job_dir(job_dir)
        if active_record:
            raise ValueError(f"任务目录已有运行中的任务: {active_record.job_id} (pid {active_record.pid})")
        api_settings = resolve_api_settings(payload, require_key=not dry_run)
        record = self.create_record(payload, dry_run=dry_run)
        log_path = record.job_dir / "webapp.log"
        log_file = log_path.open("a", encoding="utf-8")
        try:
            log_file.write("=== Web app job start ===\n")
            log_file.write(" ".join(record.command) + "\n")
            log_file.flush()
            process = subprocess.Popen(
                record.command,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(WORKSPACE_ROOT),
                env=process_env_for_api(api_settings),
            )
        finally:
            log_file.close()
        record.pid = process.pid
        record.status = "running"
        self.processes[record.job_id] = process
        self._write_record(record)
        return record

    def status(self, job_id: str) -> dict[str, Any]:
        record = self.records.get(job_id) or self._load_record(job_id)
        if not record:
            raise KeyError(job_id)
        exit_path = record.job_dir / "run.exit"
        process = self.processes.get(job_id)
        exit_code: int | None = None
        if exit_path.exists():
            try:
                exit_code = int(exit_path.read_text(encoding="utf-8").strip())
            except ValueError:
                exit_code = None
        elif process:
            poll = process.poll()
            if poll is not None:
                exit_code = poll
        if exit_code is None:
            if process or (record.status == "running" and is_process_alive(record.pid)):
                status = "running"
            elif record.status == "running":
                status = "failed"
            else:
                status = record.status
        else:
            status = "complete" if exit_code == 0 else "failed"
        record.status = status
        self._write_record(record)
        output = next((path for path in output_candidates(record.job_dir, record.payload) if path.exists()), None)
        subtitles = ensure_subtitles(record.job_dir)
        subtitle_mtime = max((path.stat().st_mtime for path in subtitles.values() if path.exists()), default=None)
        return {
            "job_id": record.job_id,
            "status": status,
            "exit_code": exit_code,
            "pid": record.pid,
            "job_dir": str(record.job_dir),
            "command": record.command,
            "log_tail": job_log_tail(record.job_dir, status, exit_code),
            "output": str(output) if output else None,
            "video_url": f"/api/jobs/{record.job_id}/video" if output else None,
            "video_mtime": output.stat().st_mtime if output else None,
            "subtitle_srt": str(subtitles.get("srt")) if subtitles.get("srt") else None,
            "subtitle_vtt": str(subtitles.get("vtt")) if subtitles.get("vtt") else None,
            "subtitle_srt_url": f"/api/jobs/{record.job_id}/subtitle.srt" if subtitles.get("srt") else None,
            "subtitle_vtt_url": f"/api/jobs/{record.job_id}/subtitle.vtt" if subtitles.get("vtt") else None,
            "subtitle_mtime": subtitle_mtime,
        }

    def video_path(self, job_id: str) -> Path:
        status = self.status(job_id)
        if not status.get("output"):
            raise FileNotFoundError(job_id)
        return Path(str(status["output"]))

    def subtitle_path(self, job_id: str, kind: str) -> Path:
        record = self.records.get(job_id) or self._load_record(job_id)
        if not record:
            raise KeyError(job_id)
        path = ensure_subtitles(record.job_dir).get(kind)
        if not path or not path.exists():
            raise FileNotFoundError(job_id)
        return path

    def _write_record(self, record: JobRecord) -> None:
        payload = {
            "job_id": record.job_id,
            "job_dir": str(record.job_dir),
            "payload": record.payload,
            "command": record.command,
            "status": record.status,
            "pid": record.pid,
        }
        (record.job_dir / "webapp_job.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.root / f"{record.job_id}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _load_record(self, job_id: str) -> JobRecord | None:
        paths = [self.root / f"{job_id}.json"]
        paths.extend(self.root.glob("*/webapp_job.json"))
        for path in paths:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("job_id") == job_id:
                record = JobRecord(
                    job_id=str(payload["job_id"]),
                    job_dir=Path(str(payload["job_dir"])),
                    payload=dict(payload.get("payload") or {}),
                    command=list(payload.get("command") or []),
                    status=str(payload.get("status") or "queued"),
                    pid=payload.get("pid"),
                )
                self.records[job_id] = record
                return record
        return None

    def _active_record_for_job_dir(self, job_dir: Path) -> JobRecord | None:
        record_path = job_dir / "webapp_job.json"
        if not record_path.exists():
            return None
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        status = str(payload.get("status") or "")
        pid = payload.get("pid")
        if status != "running" or not is_process_alive(pid):
            return None
        return JobRecord(
            job_id=str(payload.get("job_id") or ""),
            job_dir=Path(str(payload.get("job_dir") or job_dir)),
            payload=dict(payload.get("payload") or {}),
            command=list(payload.get("command") or []),
            status=status,
            pid=pid,
        )


MANAGER = JobManager(JOB_ROOT)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "MimoDubWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_static(STATIC_DIR / "index.html")
            return
        if parsed.path.startswith("/static/"):
            self.send_static(STATIC_DIR / parsed.path.removeprefix("/static/"))
            return
        if parsed.path == "/api/config":
            api_settings = resolve_api_settings({"api_key_source": "env"}, require_key=False)
            self.send_json(
                {
                    "mimo_key_set": bool(api_settings.api_key),
                    "wizard": str(WIZARD_SCRIPT),
                    "job_root": str(JOB_ROOT),
                    "env_file": str(DEFAULT_ENV_FILE),
                    "api": public_api_settings(api_settings),
                    "api_profiles": {
                        profile: {
                            "label": str(meta["label"]),
                            "base_url": str(meta["base_url"]),
                            "key_env": str(meta["key_env"]),
                        }
                        for profile, meta in API_PROFILES.items()
                    },
                }
            )
            return
        job_match = re.fullmatch(r"/api/jobs/([^/]+)", parsed.path)
        if job_match:
            self.handle_job_status(unquote(job_match.group(1)))
            return
        video_match = re.fullmatch(r"/api/jobs/([^/]+)/video", parsed.path)
        if video_match:
            self.handle_job_video(unquote(video_match.group(1)))
            return
        subtitle_match = re.fullmatch(r"/api/jobs/([^/]+)/subtitle\.(srt|vtt)", parsed.path)
        if subtitle_match:
            self.handle_job_subtitle(unquote(subtitle_match.group(1)), subtitle_match.group(2))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/analyze":
            self.handle_analyze()
            return
        if parsed.path == "/api/jobs":
            self.handle_start_job()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_analyze(self) -> None:
        try:
            payload = self.read_json()
            self.send_json(analyze_video(payload))
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_start_job(self) -> None:
        try:
            payload = self.read_json()
            dry_run = bool(payload.get("dry_run"))
            if requires_voice_consent(payload, dry_run=dry_run) and not payload.get("voice_clone_confirmed"):
                raise ValueError("voice clone consent is required before starting this job")
            record = MANAGER.start(payload, dry_run=bool(payload.get("dry_run")))
            self.send_json({"job_id": record.job_id, "status": record.status, "job_dir": str(record.job_dir)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_job_status(self, job_id: str) -> None:
        try:
            self.send_json(MANAGER.status(job_id))
        except KeyError:
            self.send_json({"error": "job not found"}, status=HTTPStatus.NOT_FOUND)

    def handle_job_video(self, job_id: str) -> None:
        try:
            path = MANAGER.video_path(job_id)
        except (KeyError, FileNotFoundError):
            self.send_json({"error": "video not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def handle_job_subtitle(self, job_id: str, kind: str) -> None:
        try:
            path = MANAGER.subtitle_path(job_id, kind)
        except (KeyError, FileNotFoundError):
            self.send_json({"error": "subtitle not found"}, status=HTTPStatus.NOT_FOUND)
            return
        content_type = "text/vtt; charset=utf-8" if kind == "vtt" else "application/x-subrip; charset=utf-8"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if kind == "srt":
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_static(self, path: Path) -> None:
        root = STATIC_DIR.resolve()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = resolved.read_bytes()
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[webapp] {self.address_string()} - {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    args = parser.parse_args()
    load_env_file(Path(args.env_file).expanduser())
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Mimo Dub Web App: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
