#!/usr/bin/env python3
"""Two-speaker Xiaomi Mimo Chinese dubbing pipeline."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import full_mimo_dub as base


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"Expected JSON object from Mimo, got: {text[:500]}")
    return json.loads(cleaned[start : end + 1])


def load_text(path: Path) -> str:
    original = path.read_text(encoding="utf-8").strip()
    normalized = base.normalize_terms(original)
    if normalized != original:
        path.write_text(normalized + "\n", encoding="utf-8")
    return normalized


def split_translate_turns(
    text_en: str,
    chunk: dict[str, Any],
    raw_path: Path,
    turns_path: Path,
    *,
    api_key: str,
    base_url: str,
    model: str,
    target_chars_per_second: float,
) -> list[dict[str, str]]:
    if turns_path.exists():
        payload = base.read_json(turns_path)
        return normalize_turns(payload.get("turns", []))
    duration = float(chunk["duration"])
    max_chars = max(40, int(duration * target_chars_per_second))
    min_chars = max(20, int(max_chars * 0.55))
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业双人访谈中文配音编剧。根据英文转录，把内容切成有序说话回合并翻译成简体中文。"
                    "只输出严格 JSON，不要 markdown，不要解释。JSON 格式必须是："
                    "{\"turns\":[{\"speaker\":\"host|guest\",\"text_zh\":\"...\"}]}。"
                    "speaker 只能是 host 或 guest。host 是主持人、旁白、广告口播者、提问者；"
                    "guest 是 Dax/受访者/opencode 创始人/主要回答者。"
                    "合并相邻同 speaker 回合，最多 5 个回合；如果不确定，按语义判断谁在提问、谁在回答。"
                    "中文要自然、口语、可直接配音，尽量完整保留信息密度和关键细节。"
                    "术语表必须原样保留：OpenCode、Open Code、open code、opencode 都统一写作 opencode；"
                    "OpenCode Zen 写作 opencode Zen；Claude Code、OpenAI、Anthropic、GitHub Copilot、Next.js 保留原文。"
                    "除术语表和常见技术缩写外，不要输出英文。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"这个音频块目标时长：{duration:.1f}秒。\n"
                    f"所有 text_zh 合计尽量在 {min_chars} 到 {max_chars} 个中文字符之间。\n"
                    "英文转录：\n"
                    f"{text_en}"
                ),
            },
        ],
        "temperature": 0.25,
        "stream": False,
    }
    response = base.mimo_post(request_payload, api_key=api_key, base_url=base_url)
    base.write_json(raw_path, response)
    parsed = extract_json_object(base.message_content(response))
    turns = normalize_turns(parsed.get("turns", []))
    if not turns:
        turns = [{"speaker": "guest", "text_zh": base.normalize_terms(text_en)}]
    base.write_json(turns_path, {"turns": turns})
    return turns


def normalize_turns(raw_turns: Any) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    if not isinstance(raw_turns, list):
        return turns
    for turn in raw_turns:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker", "")).strip().lower()
        if speaker not in {"host", "guest"}:
            speaker = "guest"
        text = base.normalize_terms(str(turn.get("text_zh", "")).strip())
        text = " ".join(text.split())
        if not text:
            continue
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["text_zh"] += text
        else:
            turns.append({"speaker": speaker, "text_zh": text})
    return turns


def synthesize_turn(
    text_zh: str,
    speaker: str,
    raw_path: Path,
    wav_path: Path,
    *,
    api_key: str,
    base_url: str,
    voice_samples: dict[str, str],
    voice_prompt: str,
) -> None:
    if wav_path.exists() and wav_path.stat().st_size > 1024:
        return
    if not text_zh:
        base.create_silence(wav_path, 0.1)
        return
    sample_data_url = voice_samples[speaker]
    payload = {
        "model": "mimo-v2.5-tts-voiceclone",
        "messages": [
            {"role": "user", "content": voice_prompt},
            {"role": "assistant", "content": text_zh},
        ],
        "audio": {
            "format": "wav",
            "voice": sample_data_url,
        },
    }
    response = base.mimo_post(payload, api_key=api_key, base_url=base_url)
    base.write_json(raw_path, response)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    wav_path.write_bytes(base.message_audio_bytes(response))


def allocate_durations(turns: list[dict[str, str]], target_duration: float, pause_duration: float) -> list[float]:
    if not turns:
        return []
    pause_total = pause_duration * max(0, len(turns) - 1)
    speech_total = max(0.1, target_duration - pause_total)
    weights = [max(1, len(turn["text_zh"])) for turn in turns]
    total_weight = sum(weights)
    durations = [speech_total * weight / total_weight for weight in weights]
    return durations


def concat_files(paths: list[Path], output: Path) -> None:
    concat_path = output.with_suffix(".concat.txt")
    concat_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path.write_text("".join(f"file {base.shell_quote(str(path))}\n" for path in paths), encoding="utf-8")
    base.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c:a", "pcm_s16le", str(output)])


def fit_turn(input_wav: Path, output_wav: Path, target_duration: float, args: argparse.Namespace) -> None:
    base.fit_audio_to_chunk(
        input_wav,
        output_wav,
        target_duration,
        max_tail_silence=args.max_turn_tail_silence,
        min_atempo_factor=args.min_atempo_factor,
    )


def synthesize_and_fit_turn(
    cid: str,
    turn_index: int,
    turn: dict[str, str],
    turn_duration: float,
    job_dir: Path,
    args: argparse.Namespace,
    *,
    api_key: str,
    api_base_url: str,
    voice_samples: dict[str, str],
) -> tuple[int, Path, dict[str, Any]]:
    speaker = turn["speaker"]
    turn_id = f"{cid}_{turn_index:02d}_{speaker}"
    tts_wav = job_dir / "tts" / f"{turn_id}.wav"
    fit_wav = job_dir / "fit_turns" / f"{turn_id}.wav"
    print(f"  [{turn_id}] TTS start", flush=True)
    synthesize_turn(
        turn["text_zh"],
        speaker,
        job_dir / "raw" / "tts" / f"{turn_id}.json",
        tts_wav,
        api_key=api_key,
        base_url=api_base_url,
        voice_samples=voice_samples,
        voice_prompt=args.voice_prompt,
    )
    fit_turn(tts_wav, fit_wav, turn_duration, args)
    print(f"  [{turn_id}] TTS+fit done", flush=True)
    return (
        turn_index,
        fit_wav,
        {
            "speaker": speaker,
            "text_zh": turn["text_zh"],
            "target_duration": turn_duration,
            "tts_duration": base.ffprobe_duration(tts_wav),
            "fit_duration": base.ffprobe_duration(fit_wav),
        },
    )


def process(args: argparse.Namespace) -> None:
    if args.env_file:
        base.load_env_file(Path(args.env_file).expanduser())
    api_key = os.environ.get(base.TOKEN_PLAN_API_KEY_ENV) or os.environ.get(base.LEGACY_API_KEY_ENV)
    if not api_key:
        raise SystemExit(f"{base.TOKEN_PLAN_API_KEY_ENV} is required in .env or the environment.")
    api_base_url = args.base_url or os.environ.get("MIMO_API_BASE_URL") or base.DEFAULT_BASE_URL

    source = Path(args.source_video).expanduser().resolve()
    job_dir = Path(args.job_dir).expanduser().resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    job = base.build_job(source, job_dir, args.chunk_duration)
    chunks = job["chunks"]
    if args.max_chunks:
        chunks = chunks[: args.max_chunks]
    print(f"Using Mimo base URL: {api_base_url}", flush=True)
    print(f"Job duration {job['duration']:.2f}s, chunks to process: {len(chunks)}", flush=True)
    tts_workers = max(1, int(args.tts_workers))
    print(f"TTS workers: {tts_workers}", flush=True)

    voice_samples = {}
    for speaker, sample_arg in {"host": args.host_voice_sample, "guest": args.guest_voice_sample}.items():
        sample_path = Path(sample_arg).expanduser().resolve()
        voice_samples[speaker], encoded_size = base.audio_data_url(sample_path)
        print(f"Using {speaker} sample: {sample_path} ({encoded_size} Base64 bytes)", flush=True)

    segment_rows: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        cid = chunk["id"]
        print(f"\n=== Chunk {cid} ({index}/{len(chunks)}) {chunk['start']:.1f}-{chunk['end']:.1f}s ===", flush=True)
        asr_text_path = job_dir / "asr" / f"{cid}.txt"
        if not asr_text_path.exists():
            raise SystemExit(f"Missing ASR text: {asr_text_path}")
        text_en = load_text(asr_text_path)
        print(f"  ASR: {text_en[:120]}", flush=True)

        turns = split_translate_turns(
            text_en,
            chunk,
            job_dir / "raw" / "turns" / f"{cid}.json",
            job_dir / "turns" / f"{cid}.json",
            api_key=api_key,
            base_url=api_base_url,
            model=args.translate_model,
            target_chars_per_second=args.target_chars_per_second,
        )
        speaker_summary = ", ".join(f"{turn['speaker']}:{len(turn['text_zh'])}" for turn in turns)
        print(f"  Turns: {speaker_summary}", flush=True)

        turn_durations = allocate_durations(turns, float(chunk["duration"]), args.pause_duration)
        chunk_parts: list[Path] = []
        turn_rows: list[dict[str, Any]] = []

        turn_jobs = list(enumerate(zip(turns, turn_durations, strict=False), start=1))
        worker_count = min(tts_workers, max(1, len(turn_jobs)))
        if worker_count == 1:
            results = [
                synthesize_and_fit_turn(
                    cid,
                    turn_index,
                    turn,
                    turn_duration,
                    job_dir,
                    args,
                    api_key=api_key,
                    api_base_url=api_base_url,
                    voice_samples=voice_samples,
                )
                for turn_index, (turn, turn_duration) in turn_jobs
            ]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        synthesize_and_fit_turn,
                        cid,
                        turn_index,
                        turn,
                        turn_duration,
                        job_dir,
                        args,
                        api_key=api_key,
                        api_base_url=api_base_url,
                        voice_samples=voice_samples,
                    )
                    for turn_index, (turn, turn_duration) in turn_jobs
                ]
                results = [future.result() for future in concurrent.futures.as_completed(futures)]

        for turn_index, fit_wav, turn_row in sorted(results, key=lambda item: item[0]):
            chunk_parts.append(fit_wav)
            turn_rows.append(turn_row)
            if turn_index < len(turns) and args.pause_duration > 0:
                pause_wav = job_dir / "fit_turns" / f"{cid}_{turn_index:02d}_pause.wav"
                base.create_silence(pause_wav, args.pause_duration)
                chunk_parts.append(pause_wav)

        chunk_fit = job_dir / "fit" / f"{cid}.wav"
        concat_files(chunk_parts, chunk_fit)
        segment_rows.append(
            {
                "id": cid,
                "start": chunk["start"],
                "end": chunk["end"],
                "duration": chunk["duration"],
                "turns": turn_rows,
                "fit_duration": base.ffprobe_duration(chunk_fit),
            }
        )
        base.write_segments(job_dir, segment_rows)

    output = Path(args.output).expanduser().resolve() if args.output else job_dir / "output" / "two_speaker_dub.mp4"
    base.assemble(job_dir, source, chunks, output)
    print(f"\nWrote {output}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--chunk-duration", type=float, default=60.0)
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url")
    parser.add_argument("--translate-model", default=base.DEFAULT_TRANSLATE_MODEL)
    parser.add_argument("--host-voice-sample", required=True)
    parser.add_argument("--guest-voice-sample", required=True)
    parser.add_argument("--target-chars-per-second", type=float, default=10.0)
    parser.add_argument("--pause-duration", type=float, default=0.2)
    parser.add_argument("--max-turn-tail-silence", type=float, default=0.4)
    parser.add_argument("--min-atempo-factor", type=float, default=0.55)
    parser.add_argument("--tts-workers", type=int, default=3, help="Concurrent TTS workers; default 3.")
    parser.add_argument(
        "--voice-prompt",
        default="使用参考音色克隆当前说话人。中文表达自然清晰，保持访谈语气，语速中等偏快，避免过度情绪化。",
    )
    return parser


def main() -> int:
    process(build_parser().parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
