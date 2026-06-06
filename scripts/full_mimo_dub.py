#!/usr/bin/env python3
"""Recoverable full-length Xiaomi Mimo YouTube Chinese dubbing pipeline."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import fcntl
import json
import math
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_TRANSLATE_MODEL = "mimo-v2.5-pro"
TOKEN_PLAN_API_KEY_ENV = "MIMO_TOKEN_PLAN_API_KEY"
LEGACY_API_KEY_ENV = "MIMO_API_KEY"
MAX_BASE64_BYTES = 10 * 1024 * 1024
TTS_SPLIT_CHAR_LIMIT = 55
TTS_SPLIT_MIN_CHARS = 90
ANTI_REPEAT_TTS_INSTRUCTION = (
    "只朗读给出的中文文本，不要添加文本外的语气词，不要说嗯、啊、咦，"
    "不要重复音节，不要拖长单个字，保持音量和声线稳定。"
)


def run(cmd: list[str]) -> None:
    if cmd and cmd[0] == "ffmpeg" and "-loglevel" not in cmd:
        cmd = [cmd[0], "-hide_banner", "-loglevel", "error", *cmd[1:]]
    print("+ " + " ".join(shell_quote(part) for part in cmd), flush=True)
    subprocess.run(cmd, check=True)


def shell_quote(value: str) -> str:
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-=.,/:@%")
    if value and all(char in safe for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


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


def ffprobe_size(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=size",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return int(result.stdout.strip())


def audio_data_url(path: Path) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        mime = "audio/wav"
    elif suffix == ".mp3":
        mime = "audio/mpeg"
    else:
        raise SystemExit(f"Mimo only accepts wav/mp3 audio samples, got: {path}")

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    encoded_size = len(encoded.encode("ascii"))
    if encoded_size > MAX_BASE64_BYTES:
        raise SystemExit(
            f"{path} Base64 size is {encoded_size} bytes, above Mimo's 10MB limit. "
            "Reduce chunk duration."
        )
    return f"data:{mime};base64,{encoded}", encoded_size


def mimo_post(payload: dict[str, Any], *, base_url: str, api_key: str, retries: int = 5) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=420) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                delay = min(60, 2 ** attempt * 3)
                print(f"  Mimo HTTP {exc.code}; retrying in {delay}s", flush=True)
                time.sleep(delay)
                continue
            raise SystemExit(f"Mimo API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, ssl.SSLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            if attempt + 1 < retries:
                delay = min(60, 2 ** attempt * 3)
                print(f"  Mimo network error {exc}; retrying in {delay}s", flush=True)
                time.sleep(delay)
                continue
            raise SystemExit(f"Mimo API request failed: {exc}") from exc

    raise SystemExit("Mimo API retry loop exhausted.")


def message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit("Unexpected Mimo response shape; inspect raw JSON.") from exc
    if not isinstance(content, str):
        raise SystemExit("Mimo response content was not text.")
    return content


def message_audio_bytes(response: dict[str, Any]) -> bytes:
    try:
        data = response["choices"][0]["message"]["audio"]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit("Unexpected Mimo TTS response shape; inspect raw JSON.") from exc
    if not isinstance(data, str):
        raise SystemExit("Mimo TTS audio data was not text.")
    return base64.b64decode(data)


def clean_asr_text(text: str) -> str:
    cleaned = text.strip()
    for tag in ("<chinese>", "</chinese>", "<english>", "</english>"):
        cleaned = cleaned.replace(tag, "")
    return normalize_terms(" ".join(cleaned.split()))


def normalize_terms(text: str) -> str:
    normalized = re.sub(r"\bopen[\s-]*code\b", "opencode", text, flags=re.IGNORECASE)
    normalized = normalized.replace("开放代码", "opencode")
    return normalized


def extract_chunk(source: Path, chunk: dict[str, Any], wav_path: Path) -> None:
    if wav_path.exists() and wav_path.stat().st_size > 1024:
        return
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{chunk['start']:.3f}",
            "-i",
            str(source),
            "-t",
            f"{chunk['duration']:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
    )


def transcribe_chunk(wav_path: Path, raw_path: Path, text_path: Path, *, api_key: str, base_url: str) -> str:
    if text_path.exists():
        original = text_path.read_text(encoding="utf-8").strip()
        normalized = normalize_terms(original)
        if normalized != original:
            text_path.write_text(normalized + "\n", encoding="utf-8")
        return normalized
    data_url, encoded_size = audio_data_url(wav_path)
    print(f"  ASR payload Base64 size: {encoded_size} bytes", flush=True)
    payload = {
        "model": "mimo-v2.5-asr",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }
                ],
            }
        ],
        "asr_options": {"language": "en"},
    }
    response = mimo_post(payload, api_key=api_key, base_url=base_url)
    write_json(raw_path, response)
    text = clean_asr_text(message_content(response))
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text + "\n", encoding="utf-8")
    return text


def translate_chunk(
    text_en: str,
    chunk: dict[str, Any],
    raw_path: Path,
    text_path: Path,
    *,
    api_key: str,
    base_url: str,
    model: str,
    target_chars_per_second: float,
) -> str:
    if text_path.exists():
        return text_path.read_text(encoding="utf-8").strip()
    if not text_en:
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("", encoding="utf-8")
        return ""

    duration = float(chunk["duration"])
    max_chars = max(40, int(duration * target_chars_per_second))
    min_chars = max(20, int(max_chars * 0.65))
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业视频中文配音翻译。把英文转成自然、口语化、可直接配音的简体中文。"
                    "不要解释，不要加括号说明，不要换行。"
                    "为了贴合原视频时长，可以压缩冗余表达，但要尽量完整保留信息密度和关键细节。"
                    "术语表必须原样保留：OpenCode、Open Code、open code、opencode 都统一写作 opencode；"
                    "OpenCode Zen 写作 opencode Zen；Claude Code、OpenAI、Anthropic、GitHub Copilot、Next.js 保留原文。"
                    "除术语表和常见技术缩写外，不要输出英文。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"目标时长：{duration:.1f}秒。\n"
                    f"中文台词长度尽量在 {min_chars} 到 {max_chars} 个中文字符之间；"
                    f"低于 {min_chars} 个字符会导致配音后长时间静音，超出 {max_chars} 个字符就是失败。\n"
                    "只输出中文配音台词：\n"
                    f"{text_en}"
                ),
            },
        ],
        "temperature": 0.4,
        "stream": False,
    }
    response = mimo_post(payload, api_key=api_key, base_url=base_url)
    write_json(raw_path, response)
    text_zh = normalize_terms(message_content(response).strip())
    text_zh = text_zh.replace("中文配音台词：", "").strip()
    text_zh = " ".join(text_zh.split())
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text_zh + "\n", encoding="utf-8")
    return text_zh


def expand_translation(
    text_en: str,
    text_zh: str,
    chunk: dict[str, Any],
    raw_path: Path,
    *,
    api_key: str,
    base_url: str,
    model: str,
    min_chars: int,
    max_chars: int,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是中文配音台词扩写师。根据英文原文和已有中文稿，输出更完整、更贴近原文的中文配音台词。"
                    "不要解释，不要换行，不要水词，不要重复凑字数。"
                    "术语表必须原样保留：OpenCode、Open Code、open code、opencode 都统一写作 opencode；"
                    "OpenCode Zen 写作 opencode Zen；Claude Code、OpenAI、Anthropic、GitHub Copilot、Next.js 保留原文。"
                    "除术语表和常见技术缩写外，不要输出英文。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"目标时长：{float(chunk['duration']):.1f}秒。\n"
                    f"中文台词长度必须在 {min_chars} 到 {max_chars} 个中文字符之间。\n"
                    "英文原文：\n"
                    f"{text_en}\n"
                    "已有中文稿：\n"
                    f"{text_zh}\n"
                    "只输出扩写后的中文配音台词："
                ),
            },
        ],
        "temperature": 0.3,
        "stream": False,
    }
    response = mimo_post(payload, api_key=api_key, base_url=base_url)
    write_json(raw_path, response)
    expanded = normalize_terms(message_content(response).strip())
    expanded = expanded.replace("扩写后的中文配音台词：", "").strip()
    return " ".join(expanded.split())


def shorten_translation(
    text_zh: str,
    chunk: dict[str, Any],
    raw_path: Path,
    *,
    api_key: str,
    base_url: str,
    model: str,
    max_chars: int,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是中文配音台词压缩师。只保留核心意思，输出一段自然口语中文。"
                    "不要解释，不要换行。"
                    "术语表必须原样保留：OpenCode、Open Code、open code、opencode 都统一写作 opencode；"
                    "OpenCode Zen 写作 opencode Zen；Claude Code、OpenAI、Anthropic、GitHub Copilot、Next.js 保留原文。"
                    "除术语表和常见技术缩写外，不要输出英文。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"目标时长：{float(chunk['duration']):.1f}秒。\n"
                    f"必须压缩到 {max_chars} 个中文字符以内。\n"
                    "只输出压缩后的中文台词：\n"
                    f"{text_zh}"
                ),
            },
        ],
        "temperature": 0.2,
        "stream": False,
    }
    response = mimo_post(payload, api_key=api_key, base_url=base_url)
    write_json(raw_path, response)
    shortened = normalize_terms(message_content(response).strip())
    shortened = shortened.replace("压缩后的中文台词：", "").strip()
    return " ".join(shortened.split())


def split_text_for_tts(text: str, *, max_chars: int = TTS_SPLIT_CHAR_LIMIT) -> list[str]:
    units = re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text) or [text]
    parts: list[str] = []
    current = ""
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        if len(unit) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(unit[index : index + max_chars].strip() for index in range(0, len(unit), max_chars))
            continue
        if current and len(current) + len(unit) > max_chars:
            parts.append(current)
            current = unit
        else:
            current += unit
    if current:
        parts.append(current)
    return [part for part in parts if part]


def tts_payload(
    text_zh: str,
    *,
    voice_strategy: str,
    voice_prompt: str,
    voice_sample_data_url: str | None,
) -> dict[str, Any]:
    prompt = " ".join(part for part in [voice_prompt.strip(), ANTI_REPEAT_TTS_INSTRUCTION] if part)
    if voice_strategy == "voice-clone":
        if not voice_sample_data_url:
            raise SystemExit("--voice-sample is required when --voice-strategy voice-clone.")
        return {
            "model": "mimo-v2.5-tts-voiceclone",
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": text_zh},
            ],
            "audio": {
                "format": "wav",
                "voice": voice_sample_data_url,
            },
        }
    if voice_strategy == "voice-design":
        return {
            "model": "mimo-v2.5-tts-voicedesign",
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": text_zh},
            ],
            "audio": {
                "format": "wav",
                "optimize_text_preview": False,
            },
        }
    raise SystemExit(f"Unsupported voice strategy: {voice_strategy}")


def write_tts_response(
    payload: dict[str, Any],
    raw_path: Path,
    wav_path: Path,
    *,
    api_key: str,
    base_url: str,
) -> None:
    response = mimo_post(payload, api_key=api_key, base_url=base_url)
    write_json(raw_path, response)
    atomic_write_bytes(wav_path, message_audio_bytes(response))


def concat_wavs(inputs: list[Path], output: Path) -> None:
    missing = [path for path in inputs if not path.exists() or path.stat().st_size <= 1024]
    if missing:
        missing_list = ", ".join(str(path) for path in missing[:5])
        raise RuntimeError(f"Missing or invalid TTS split parts before concat: {missing_list}")
    concat_file = output.with_suffix(".concat.txt")
    concat_file.parent.mkdir(parents=True, exist_ok=True)
    concat_file.write_text("".join(f"file {shell_quote(str(path))}\n" for path in inputs), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "pcm_s16le", str(output)])


def synthesize_chunk(
    text_zh: str,
    raw_path: Path,
    wav_path: Path,
    *,
    api_key: str,
    base_url: str,
    voice_strategy: str,
    voice_prompt: str,
    voice_sample_data_url: str | None,
) -> None:
    with file_lock(wav_path.with_suffix(wav_path.suffix + ".lock")):
        return synthesize_chunk_locked(
            text_zh,
            raw_path,
            wav_path,
            api_key=api_key,
            base_url=base_url,
            voice_strategy=voice_strategy,
            voice_prompt=voice_prompt,
            voice_sample_data_url=voice_sample_data_url,
        )


def synthesize_chunk_locked(
    text_zh: str,
    raw_path: Path,
    wav_path: Path,
    *,
    api_key: str,
    base_url: str,
    voice_strategy: str,
    voice_prompt: str,
    voice_sample_data_url: str | None,
) -> None:
    if wav_path.exists() and wav_path.stat().st_size > 1024:
        return
    if not text_zh:
        create_silence(wav_path, 0.1)
        return
    parts = split_text_for_tts(text_zh)
    if len(text_zh) >= TTS_SPLIT_MIN_CHARS and len(parts) > 1:
        print(f"  Splitting long TTS text into {len(parts)} shorter calls", flush=True)
        part_dir = wav_path.parent / f"{wav_path.stem}_parts"
        raw_part_dir = raw_path.parent / f"{raw_path.stem}_parts"
        cached_parts_match = False
        if raw_path.exists():
            try:
                cached_manifest = read_json(raw_path)
                cached_parts = [str(item.get("text") or "") for item in cached_manifest.get("parts", [])]
                cached_parts_match = cached_manifest.get("strategy") == "split-tts" and cached_parts == parts
            except (json.JSONDecodeError, OSError, AttributeError):
                cached_parts_match = False
        if not cached_parts_match and part_dir.exists():
            for stale_part in part_dir.glob("*.wav"):
                stale_part.unlink()
        part_wavs: list[Path] = []
        for index, part in enumerate(parts, start=1):
            part_wav = part_dir / f"{index:02d}.wav"
            part_raw = raw_part_dir / f"{index:02d}.json"
            part_wavs.append(part_wav)
            if part_wav.exists() and part_wav.stat().st_size > 1024:
                continue
            payload = tts_payload(
                part,
                voice_strategy=voice_strategy,
                voice_prompt=voice_prompt,
                voice_sample_data_url=voice_sample_data_url,
            )
            write_tts_response(payload, part_raw, part_wav, api_key=api_key, base_url=base_url)
        write_json(
            raw_path,
            {
                "strategy": "split-tts",
                "part_count": len(parts),
                "char_limit": TTS_SPLIT_CHAR_LIMIT,
                "parts": [{"index": index, "text": part} for index, part in enumerate(parts, start=1)],
            },
        )
        concat_wavs(part_wavs, wav_path)
        return

    payload = tts_payload(
        text_zh,
        voice_strategy=voice_strategy,
        voice_prompt=voice_prompt,
        voice_sample_data_url=voice_sample_data_url,
    )
    write_tts_response(payload, raw_path, wav_path, api_key=api_key, base_url=base_url)


def atempo_filter(factor: float) -> str:
    parts: list[str] = []
    remaining = factor
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def fit_audio_to_chunk(
    input_wav: Path,
    output_wav: Path,
    target_duration: float,
    *,
    max_tail_silence: float,
    min_atempo_factor: float,
) -> None:
    current = ffprobe_duration(input_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    if current <= 0.05:
        create_silence(output_wav, target_duration)
        return
    if current > target_duration:
        factor = current / max(0.1, target_duration)
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_wav),
                "-filter:a",
                atempo_filter(factor),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output_wav),
            ]
        )
        current = ffprobe_duration(output_wav)
    else:
        desired_speech_duration = current
        if target_duration - current > max_tail_silence:
            desired_speech_duration = min(target_duration, max(target_duration - max_tail_silence, current))
            desired_speech_duration = min(desired_speech_duration, current / max(0.5, min_atempo_factor))
        tempo_factor = current / max(0.1, desired_speech_duration)
        filter_args = []
        if abs(tempo_factor - 1.0) > 0.01:
            filter_args = ["-filter:a", atempo_filter(tempo_factor)]
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_wav),
                *filter_args,
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output_wav),
            ]
        )
        current = ffprobe_duration(output_wav)
    if current < target_duration - 0.02:
        silence = output_wav.with_suffix(".tail.wav")
        create_silence(silence, target_duration - current)
        concat_file = output_wav.with_suffix(".concat.txt")
        concat_file.write_text(
            f"file {shell_quote(str(output_wav))}\nfile {shell_quote(str(silence))}\n",
            encoding="utf-8",
        )
        padded = output_wav.with_suffix(".padded.wav")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "pcm_s16le", str(padded)])
        padded.replace(output_wav)


def create_silence(path: Path, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t",
            f"{max(0.01, duration):.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def build_job(source: Path, job_dir: Path, chunk_duration: float) -> dict[str, Any]:
    manifest_path = job_dir / "job.json"
    if manifest_path.exists():
        existing = read_json(manifest_path)
        if isinstance(existing.get("chunks"), list) and "duration" in existing:
            return existing
    else:
        existing = {}

    duration = ffprobe_duration(source)
    chunks = []
    count = int(math.ceil(duration / chunk_duration))
    for index in range(count):
        start = index * chunk_duration
        dur = min(chunk_duration, max(0.0, duration - start))
        if dur <= 0.05:
            continue
        chunks.append(
            {
                "id": f"{index + 1:04d}",
                "start": start,
                "end": start + dur,
                "duration": dur,
            }
        )
    job = dict(existing)
    job.update(
        {
            "full_pipeline_created_by": "mimo-youtube-chinese-dub-full-pipeline",
            "source_video": str(source.resolve()),
            "duration": duration,
            "chunk_duration": chunk_duration,
            "chunks": chunks,
        }
    )
    write_json(manifest_path, job)
    return job


def write_segments(job_dir: Path, rows: list[dict[str, Any]]) -> None:
    write_json(job_dir / "segments.zh.json", rows)


def assemble(job_dir: Path, source_video: Path, chunks: list[dict[str, Any]], output: Path) -> None:
    concat_file = job_dir / "fit" / "concat.txt"
    concat_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for chunk in chunks:
        lines.append(f"file {shell_quote(str(job_dir / 'fit' / f'{chunk['id']}.wav'))}\n")
    concat_file.write_text("".join(lines), encoding="utf-8")
    dubbed_audio = job_dir / "output" / "dubbed_audio.wav"
    dubbed_audio.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "pcm_s16le", str(dubbed_audio)])
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(dubbed_audio),
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
    )


def synthesize_and_fit_segment(
    row: dict[str, Any],
    chunk: dict[str, Any],
    job_dir: Path,
    args: argparse.Namespace,
    *,
    api_key: str | None,
    base_url: str,
    voice_sample_data_url: str | None,
) -> dict[str, Any]:
    cid = str(row["id"])
    text_en = str(row.get("text_en") or "")
    text_zh = str(row.get("text_zh") or "")
    trans_text_path = job_dir / "zh" / f"{cid}.txt"
    raw_tts_path = job_dir / "raw" / "tts" / f"{cid}.json"
    raw_shorten_dir = job_dir / "raw" / "shorten"
    tts_wav = job_dir / "tts" / f"{cid}.wav"
    fit_wav = job_dir / "fit" / f"{cid}.wav"

    if not args.no_api:
        if not api_key:
            raise SystemExit(f"{TOKEN_PLAN_API_KEY_ENV} is required in .env or the environment.")
        print(f"  [{cid}] TTS start", flush=True)
        synthesize_chunk(
            text_zh,
            raw_tts_path,
            tts_wav,
            api_key=api_key,
            base_url=base_url,
            voice_strategy=args.voice_strategy,
            voice_prompt=args.voice_prompt,
            voice_sample_data_url=voice_sample_data_url,
        )
        for retry in range(args.max_tts_expand_retries):
            tts_duration = ffprobe_duration(tts_wav)
            target_duration = float(chunk["duration"])
            min_tts_duration = max(0.1, (target_duration - args.max_tail_silence) * args.min_atempo_factor)
            if tts_duration >= min_tts_duration or not text_en:
                break
            expand_min_chars = max(
                len(text_zh) + 60,
                int(len(text_zh) * min_tts_duration / max(0.1, tts_duration) * 1.05),
            )
            expand_max_chars = max(expand_min_chars + 80, int(target_duration * args.target_chars_per_second))
            print(
                f"  [{cid}] TTS {tts_duration:.2f}s is too short for target {target_duration:.2f}s; "
                f"expanding to {expand_min_chars}-{expand_max_chars} chars "
                f"(retry {retry + 1}/{args.max_tts_expand_retries})",
                flush=True,
            )
            text_zh = expand_translation(
                text_en,
                text_zh,
                chunk,
                raw_shorten_dir / f"{cid}_expand_{retry + 1}.json",
                api_key=api_key,
                base_url=base_url,
                model=args.translate_model,
                min_chars=expand_min_chars,
                max_chars=expand_max_chars,
            )
            trans_text_path.write_text(text_zh + "\n", encoding="utf-8")
            if tts_wav.exists():
                tts_wav.unlink()
            synthesize_chunk(
                text_zh,
                raw_tts_path,
                tts_wav,
                api_key=api_key,
                base_url=base_url,
                voice_strategy=args.voice_strategy,
                voice_prompt=args.voice_prompt,
                voice_sample_data_url=voice_sample_data_url,
            )
        for retry in range(args.max_tts_retries):
            tts_duration = ffprobe_duration(tts_wav)
            target_duration = float(chunk["duration"])
            if tts_duration <= target_duration * 1.15:
                break
            new_max_chars = max(28, int(len(text_zh) * target_duration / tts_duration * 0.9))
            print(
                f"  [{cid}] TTS {tts_duration:.2f}s exceeds target {target_duration:.2f}s; "
                f"shortening to {new_max_chars} chars (retry {retry + 1}/{args.max_tts_retries})",
                flush=True,
            )
            text_zh = shorten_translation(
                text_zh,
                chunk,
                raw_shorten_dir / f"{cid}_tts_{retry + 1}.json",
                api_key=api_key,
                base_url=base_url,
                model=args.translate_model,
                max_chars=new_max_chars,
            )
            trans_text_path.write_text(text_zh + "\n", encoding="utf-8")
            if tts_wav.exists():
                tts_wav.unlink()
            synthesize_chunk(
                text_zh,
                raw_tts_path,
                tts_wav,
                api_key=api_key,
                base_url=base_url,
                voice_strategy=args.voice_strategy,
                voice_prompt=args.voice_prompt,
                voice_sample_data_url=voice_sample_data_url,
            )

    if not tts_wav.exists():
        create_silence(tts_wav, 0.1)
    fit_audio_to_chunk(
        tts_wav,
        fit_wav,
        float(chunk["duration"]),
        max_tail_silence=args.max_tail_silence,
        min_atempo_factor=args.min_atempo_factor,
    )
    updated = dict(row)
    updated.update(
        {
            "text_zh": text_zh,
            "tts_duration": ffprobe_duration(tts_wav) if tts_wav.exists() else None,
            "fit_duration": ffprobe_duration(fit_wav) if fit_wav.exists() else None,
        }
    )
    print(f"  [{cid}] TTS+fit done", flush=True)
    return updated


def process(args: argparse.Namespace) -> None:
    if args.env_file:
        load_env_file(Path(args.env_file).expanduser())
    api_key_env_name = TOKEN_PLAN_API_KEY_ENV if os.environ.get(TOKEN_PLAN_API_KEY_ENV) else LEGACY_API_KEY_ENV
    api_key = os.environ.get(api_key_env_name)
    if not api_key and not args.no_api:
        raise SystemExit(f"{TOKEN_PLAN_API_KEY_ENV} is required in .env or the environment.")
    base_url = args.base_url or os.environ.get("MIMO_API_BASE_URL") or DEFAULT_BASE_URL
    if not args.no_api:
        print(f"Using Mimo base URL: {base_url}", flush=True)
        print(f"Using API key env: {api_key_env_name}", flush=True)
    source = Path(args.source_video).expanduser().resolve()
    job_dir = Path(args.job_dir).expanduser().resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    voice_sample_data_url = None
    if args.voice_strategy == "voice-clone":
        if not args.voice_sample:
            raise SystemExit("--voice-sample is required when --voice-strategy voice-clone.")
        voice_sample_path = Path(args.voice_sample).expanduser().resolve()
        voice_sample_data_url, encoded_size = audio_data_url(voice_sample_path)
        print(f"Using voice clone sample: {voice_sample_path} ({encoded_size} Base64 bytes)", flush=True)
    job = build_job(source, job_dir, args.chunk_duration)
    chunks = job["chunks"]
    if args.max_chunks:
        chunks = chunks[: args.max_chunks]
    print(f"Job duration {job['duration']:.2f}s, chunks to process: {len(chunks)}", flush=True)

    segment_rows: list[dict[str, Any]] = []
    chunk_by_id: dict[str, dict[str, Any]] = {}
    for index, chunk in enumerate(chunks, start=1):
        cid = chunk["id"]
        chunk_by_id[cid] = chunk
        print(f"\n=== Chunk {cid} ({index}/{len(chunks)}) {chunk['start']:.1f}-{chunk['end']:.1f}s ===", flush=True)
        chunk_wav = job_dir / "chunks" / f"{cid}.wav"
        extract_chunk(source, chunk, chunk_wav)

        asr_text_path = job_dir / "asr" / f"{cid}.txt"
        trans_text_path = job_dir / "zh" / f"{cid}.txt"
        raw_asr_path = job_dir / "raw" / "asr" / f"{cid}.json"
        raw_translate_path = job_dir / "raw" / "translate" / f"{cid}.json"
        raw_shorten_dir = job_dir / "raw" / "shorten"

        if args.no_api:
            text_en = asr_text_path.read_text(encoding="utf-8").strip() if asr_text_path.exists() else ""
            text_zh = trans_text_path.read_text(encoding="utf-8").strip() if trans_text_path.exists() else ""
        else:
            text_en = transcribe_chunk(chunk_wav, raw_asr_path, asr_text_path, api_key=api_key, base_url=base_url)
            print(f"  ASR: {text_en[:120]}", flush=True)
            text_zh = translate_chunk(
                text_en,
                chunk,
                raw_translate_path,
                trans_text_path,
                api_key=api_key,
                base_url=base_url,
                model=args.translate_model,
                target_chars_per_second=args.target_chars_per_second,
            )
            max_chars = max(40, int(float(chunk["duration"]) * args.target_chars_per_second))
            if len(text_zh) > int(max_chars * 1.15):
                print(f"  Translation is long ({len(text_zh)} chars); shortening to {max_chars}", flush=True)
                text_zh = shorten_translation(
                    text_zh,
                    chunk,
                    raw_shorten_dir / f"{cid}_length.json",
                    api_key=api_key,
                    base_url=base_url,
                    model=args.translate_model,
                    max_chars=max_chars,
                )
                trans_text_path.write_text(text_zh + "\n", encoding="utf-8")
            print(f"  ZH: {text_zh[:90]}", flush=True)
        segment_rows.append(
            {
                "id": cid,
                "start": chunk["start"],
                "end": chunk["end"],
                "duration": chunk["duration"],
                "text_en": text_en,
                "text_zh": text_zh,
                "tts_duration": None,
                "fit_duration": None,
            }
        )
        write_segments(job_dir, segment_rows)

    tts_workers = max(1, int(args.tts_workers))
    worker_count = min(tts_workers, max(1, len(segment_rows)))
    print(f"\nTTS workers: {worker_count}", flush=True)

    def update_completed_row(row: dict[str, Any]) -> None:
        for index, existing in enumerate(segment_rows):
            if existing["id"] == row["id"]:
                segment_rows[index] = row
                break
        write_segments(job_dir, segment_rows)

    if worker_count == 1:
        for row in segment_rows:
            update_completed_row(
                synthesize_and_fit_segment(
                    row,
                    chunk_by_id[str(row["id"])],
                    job_dir,
                    args,
                    api_key=api_key,
                    base_url=base_url,
                    voice_sample_data_url=voice_sample_data_url,
                )
            )
    else:
        failed_rows: list[tuple[str, BaseException]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    synthesize_and_fit_segment,
                    row,
                    chunk_by_id[str(row["id"])],
                    job_dir,
                    args,
                    api_key=api_key,
                    base_url=base_url,
                    voice_sample_data_url=voice_sample_data_url,
                ): str(row["id"])
                for row in segment_rows
            }
            for future in concurrent.futures.as_completed(futures):
                cid = futures[future]
                try:
                    update_completed_row(future.result())
                except Exception as exc:
                    print(f"  [{cid}] TTS worker failed; will retry serially after other workers finish: {exc}", flush=True)
                    failed_rows.append((cid, exc))
        for cid, _exc in failed_rows:
            row = next(row for row in segment_rows if str(row["id"]) == cid)
            print(f"  [{cid}] Retrying TTS+fit serially", flush=True)
            update_completed_row(
                synthesize_and_fit_segment(
                    row,
                    chunk_by_id[cid],
                    job_dir,
                    args,
                    api_key=api_key,
                    base_url=base_url,
                    voice_sample_data_url=voice_sample_data_url,
                )
            )

    output = Path(args.output).expanduser().resolve() if args.output else job_dir / "output" / "full_chinese_dub.mp4"
    assemble(job_dir, source, chunks, output)
    print(f"\nWrote {output}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--chunk-duration", type=float, default=30.0)
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--translate-model", default=DEFAULT_TRANSLATE_MODEL)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url")
    parser.add_argument("--target-chars-per-second", type=float, default=10.0)
    parser.add_argument("--max-tail-silence", type=float, default=0.6)
    parser.add_argument("--min-atempo-factor", type=float, default=0.55)
    parser.add_argument("--tts-workers", type=int, default=3, help="Concurrent TTS workers; default 3.")
    parser.add_argument("--max-tts-retries", type=int, default=2)
    parser.add_argument("--max-tts-expand-retries", type=int, default=1)
    parser.add_argument("--voice-strategy", default="voice-design", choices=["voice-design", "voice-clone"])
    parser.add_argument("--voice-sample")
    parser.add_argument(
        "--voice-prompt",
        default="温暖清晰的中文技术访谈旁白，中速偏快，沉稳可信，表达自然，不夸张。",
    )
    parser.add_argument("--no-api", action="store_true", help="Only assemble from existing transcript/translation/TTS files.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    process(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
